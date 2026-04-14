"""시세 감시 (워치리스트) — 목표가 도달 시 알림."""

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from src.config import DATA_DIR
from src.market.api import get_item_price

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "watchlist.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_watchlist_db() -> None:
    """워치리스트 DB 초기화."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                item_name TEXT NOT NULL,
                target_price INTEGER NOT NULL,
                current_price INTEGER,
                status TEXT NOT NULL DEFAULT 'watching',
                created_at TEXT NOT NULL,
                triggered_at TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_watchlist_user
            ON watchlist (user_name, status)
        """)
    logger.info("워치리스트 DB 초기화: %s", DB_PATH)


@dataclass
class WatchItem:
    id: int
    user_name: str
    item_slug: str
    item_name: str
    target_price: int
    current_price: int | None
    status: str  # "watching", "triggered"
    created_at: str
    triggered_at: str | None


def add_watch(user_name: str, item_slug: str, item_name: str, target_price: int) -> int | str:
    """감시 항목 추가. 성공 시 id, 실패 시 에러 메시지."""
    if not user_name or len(user_name) > 20:
        return "유저 이름은 1~20자로 입력해주세요."
    if not item_slug:
        return "아이템을 선택해주세요."
    if not isinstance(target_price, int) or target_price < 1:
        return "목표가는 1p 이상이어야 합니다."

    # 중복 체크
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM watchlist WHERE user_name = ? AND item_slug = ? AND status = 'watching'",
            (user_name, item_slug),
        ).fetchone()
        if existing:
            return "이미 감시 중인 아이템입니다."

        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "INSERT INTO watchlist (user_name, item_slug, item_name, target_price, status, created_at)"
            " VALUES (?, ?, ?, ?, 'watching', ?)",
            (user_name, item_slug, item_name, target_price, now),
        )
        return cursor.lastrowid


def remove_watch(watch_id: int, user_name: str) -> bool:
    """감시 항목 삭제."""
    with _get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM watchlist WHERE id = ? AND user_name = ?",
            (watch_id, user_name),
        )
    return cursor.rowcount > 0


def get_user_watches(user_name: str) -> list[WatchItem]:
    """유저의 감시 목록."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, user_name, item_slug, item_name, target_price,"
            " current_price, status, created_at, triggered_at"
            " FROM watchlist WHERE user_name = ? ORDER BY created_at DESC",
            (user_name,),
        ).fetchall()
    return [
        WatchItem(
            id=r[0], user_name=r[1], item_slug=r[2], item_name=r[3],
            target_price=r[4], current_price=r[5], status=r[6],
            created_at=r[7], triggered_at=r[8],
        )
        for r in rows
    ]


def get_all_active_watches() -> list[WatchItem]:
    """모든 활성 감시 항목 (폴링용)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, user_name, item_slug, item_name, target_price,"
            " current_price, status, created_at, triggered_at"
            " FROM watchlist WHERE status = 'watching'",
        ).fetchall()
    return [
        WatchItem(
            id=r[0], user_name=r[1], item_slug=r[2], item_name=r[3],
            target_price=r[4], current_price=r[5], status=r[6],
            created_at=r[7], triggered_at=r[8],
        )
        for r in rows
    ]


def _update_watch(watch_id: int, current_price: int, triggered: bool) -> None:
    """감시 항목 가격 업데이트."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        if triggered:
            conn.execute(
                "UPDATE watchlist SET current_price = ?, status = 'triggered', triggered_at = ?"
                " WHERE id = ?",
                (current_price, now, watch_id),
            )
        else:
            conn.execute(
                "UPDATE watchlist SET current_price = ? WHERE id = ?",
                (current_price, watch_id),
            )


def update_watch_price(watch_id: int, current_price: int) -> None:
    """단일 감시 항목 현재가 즉시 갱신 (등록 직후 초기화용)."""
    _update_watch(watch_id, current_price, triggered=False)


async def check_watches(broadcast_fn=None) -> list[dict]:
    """활성 감시 항목들의 가격을 체크하고 도달 시 알림."""
    watches = get_all_active_watches()
    if not watches:
        return []

    # slug별로 그룹화 (같은 아이템 중복 조회 방지)
    by_slug: dict[str, list[WatchItem]] = {}
    for w in watches:
        by_slug.setdefault(w.item_slug, []).append(w)

    triggered = []

    for slug, items in by_slug.items():
        try:
            price = await get_item_price(slug)
            if not price or price.sell_min is None:
                continue

            current = price.sell_min
            for w in items:
                _update_watch(w.id, current, triggered=current <= w.target_price)
                if current <= w.target_price:
                    alert = {
                        "user_name": w.user_name,
                        "item_name": w.item_name,
                        "item_slug": w.item_slug,
                        "target_price": w.target_price,
                        "current_price": current,
                    }
                    triggered.append(alert)
                    logger.info(
                        "시세 감시 도달: %s — %s 목표 %dp, 현재 %dp",
                        w.user_name, w.item_name, w.target_price, current,
                    )

                    if broadcast_fn:
                        await broadcast_fn({
                            "type": "alert",
                            "text": f"💰 시세 도달! {w.item_name} — "
                                    f"현재 {current}p (목표 {w.target_price}p 이하)",
                        })
        except Exception:
            logger.warning("워치리스트 체크 실패: %s", slug, exc_info=True)

    return triggered


async def run_watchlist_monitor(broadcast_fn=None) -> None:
    """워치리스트 백그라운드 모니터링 루프 (5분 간격)."""
    logger.info("워치리스트 모니터 시작")
    while True:
        try:
            triggered = await check_watches(broadcast_fn)
            if triggered:
                logger.info("워치리스트 알림 %d건 발송", len(triggered))
        except Exception:
            logger.exception("워치리스트 모니터 오류")
        await asyncio.sleep(300)  # 5분
