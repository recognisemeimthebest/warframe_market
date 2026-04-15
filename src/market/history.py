"""시세 히스토리 저장/조회 (SQLite)."""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "price_history.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    """DB 테이블 생성."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL,
                rank INTEGER,
                sell_min INTEGER,
                sell_2nd INTEGER,
                sell_count INTEGER DEFAULT 0,
                buy_max INTEGER,
                buy_count INTEGER DEFAULT 0,
                avg_price REAL,
                volume INTEGER DEFAULT 0,
                scanned_at TEXT NOT NULL
            )
        """)
        # 기존 DB 마이그레이션 (sell_2nd 컬럼 없는 경우)
        try:
            conn.execute("ALTER TABLE price_snapshot ADD COLUMN sell_2nd INTEGER")
        except Exception:
            pass  # 이미 존재
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshot_slug_rank_time
            ON price_snapshot (slug, rank, scanned_at)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS surge_alert (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL,
                period TEXT NOT NULL,
                rank INTEGER,
                old_price REAL NOT NULL,
                new_price REAL NOT NULL,
                change_pct REAL NOT NULL,
                detected_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_surge_time
            ON surge_alert (detected_at DESC)
        """)
    logger.info("시세 DB 초기화: %s", DB_PATH)


def save_snapshot(slug: str, sell_min: int | None, sell_count: int,
                  buy_max: int | None, buy_count: int,
                  avg_price: float | None, volume: int,
                  rank: int | None = None,
                  sell_2nd: int | None = None) -> None:
    """시세 스냅샷 1개 저장. rank=None이면 전체, 0이면 0랭, N이면 N랭."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO price_snapshot (slug, rank, sell_min, sell_2nd, sell_count, buy_max, buy_count, avg_price, volume, scanned_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slug, rank, sell_min, sell_2nd, sell_count, buy_max, buy_count, avg_price, volume, now),
        )


def _best_price(row) -> float | None:
    """sell_min 또는 avg_price 중 유효한 값 반환."""
    if row is None:
        return None
    sell_min, avg_price = row
    if sell_min is not None:
        return float(sell_min)
    if avg_price is not None:
        return float(avg_price)
    return None


def get_price_at(slug: str, hours_ago: int, rank: int | None = None) -> float | None:
    """N시간 전 가격 (±1시간 범위). sell_min 없으면 avg_price 사용."""
    now = datetime.now(timezone.utc)
    target = now - timedelta(hours=hours_ago)
    window_start = (target - timedelta(hours=1)).isoformat()
    window_end = (target + timedelta(hours=1)).isoformat()

    rank_clause = "AND rank IS NULL" if rank is None else "AND rank = ?"
    params = [slug, window_start, window_end] + ([] if rank is None else [rank])

    with _get_conn() as conn:
        row = conn.execute(
            "SELECT AVG(sell_min), AVG(avg_price) FROM price_snapshot"
            f" WHERE slug = ? AND scanned_at BETWEEN ? AND ? {rank_clause}",
            params,
        ).fetchone()
    return _best_price(row)


def get_price_days_ago(slug: str, days_ago: int, rank: int | None = None) -> float | None:
    """N일 전 가격 (±12시간 범위). sell_min 없으면 avg_price 사용."""
    now = datetime.now(timezone.utc)
    target = now - timedelta(days=days_ago)
    window_start = (target - timedelta(hours=12)).isoformat()
    window_end = (target + timedelta(hours=12)).isoformat()

    rank_clause = "AND rank IS NULL" if rank is None else "AND rank = ?"
    params = [slug, window_start, window_end] + ([] if rank is None else [rank])

    with _get_conn() as conn:
        row = conn.execute(
            "SELECT AVG(sell_min), AVG(avg_price) FROM price_snapshot"
            f" WHERE slug = ? AND scanned_at BETWEEN ? AND ? {rank_clause}",
            params,
        ).fetchone()
    return _best_price(row)


def get_current_price(slug: str, rank: int | None = None) -> float | None:
    """최근 스냅샷의 판매 최저가 (없으면 avg_price)."""
    rank_clause = "AND rank IS NULL" if rank is None else "AND rank = ?"
    params = [slug] + ([] if rank is None else [rank])

    with _get_conn() as conn:
        row = conn.execute(
            "SELECT sell_min, avg_price FROM price_snapshot"
            f" WHERE slug = ? {rank_clause}"
            " ORDER BY scanned_at DESC LIMIT 1",
            params,
        ).fetchone()
    return _best_price(row) if row else None


@dataclass
class SurgeItem:
    """급등 감지 결과."""
    slug: str
    period: str        # "1d", "7d", "30d"
    old_price: float
    new_price: float
    change_pct: float  # 변동률 (%)
    rank: int | None = None  # None=전체, 0=0랭, N=N랭(MAX)


def save_surge(surge: SurgeItem) -> None:
    """급등 알림 저장."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO surge_alert (slug, period, rank, old_price, new_price, change_pct, detected_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (surge.slug, surge.period, surge.rank, surge.old_price, surge.new_price, surge.change_pct, now),
        )


def get_recent_surges(limit: int = 50) -> list[dict]:
    """최근 급등 알림 목록."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT slug, period, rank, old_price, new_price, change_pct, detected_at"
            " FROM surge_alert ORDER BY detected_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "slug": r[0], "period": r[1], "rank": r[2],
            "old_price": r[3], "new_price": r[4],
            "change_pct": round(r[5], 1), "detected_at": r[6],
        }
        for r in rows
    ]


def get_stored_ranks(slug: str) -> list[int]:
    """DB에 저장된 해당 아이템의 랭크 목록 (0, MAX 등)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT rank FROM price_snapshot WHERE slug = ? AND rank IS NOT NULL",
            (slug,),
        ).fetchall()
    return [r[0] for r in rows]


def cleanup_old_data(keep_days: int = 90) -> int:
    """오래된 스냅샷 삭제."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    with _get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM price_snapshot WHERE scanned_at < ?", (cutoff,)
        )
        deleted = cursor.rowcount
    if deleted:
        logger.info("오래된 스냅샷 %d개 삭제", deleted)
    return deleted


_DEFAULT_ALERT_CONFIG = {
    "threshold_1d": 20.0,
    "threshold_7d": 30.0,
    "threshold_30d": 50.0,
    "min_price": 5,
}


def get_alert_config() -> dict:
    """알림 기준 설정 조회. 없으면 기본값 반환."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM alert_config").fetchall()
    cfg = dict(_DEFAULT_ALERT_CONFIG)
    for k, v in rows:
        try:
            cfg[k] = float(v) if "threshold" in k else int(v)
        except ValueError:
            pass
    return cfg


def save_alert_config(cfg: dict) -> None:
    """알림 기준 설정 저장."""
    with _get_conn() as conn:
        for k, v in cfg.items():
            conn.execute(
                "INSERT OR REPLACE INTO alert_config (key, value) VALUES (?, ?)",
                (k, str(v)),
            )


def get_price_trend(slug: str, days: int = 7) -> dict | None:
    """최근 N일 가격 추세 계산.

    Returns:
        {
            "direction": "up" | "down" | "flat",
            "change_pct": float,        # 기간 변동률 (%)
            "price_now": float,
            "price_start": float,
            "data_points": int,
        }
        None이면 데이터 부족.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT scanned_at,
                   COALESCE(avg_price, sell_min) AS price
            FROM price_snapshot
            WHERE slug = ? AND rank IS NULL AND scanned_at >= ?
              AND COALESCE(avg_price, sell_min) IS NOT NULL
            ORDER BY scanned_at ASC
            """,
            (slug, cutoff),
        ).fetchall()

    if len(rows) < 2:
        return None

    prices = [r[1] for r in rows if r[1] is not None]
    if len(prices) < 2:
        return None

    price_start = prices[0]
    price_now = prices[-1]

    if price_start <= 0:
        return None

    change_pct = (price_now - price_start) / price_start * 100

    if change_pct >= 5:
        direction = "up"
    elif change_pct <= -5:
        direction = "down"
    else:
        direction = "flat"

    return {
        "direction": direction,
        "change_pct": round(change_pct, 1),
        "price_now": round(price_now, 1),
        "price_start": round(price_start, 1),
        "data_points": len(prices),
    }


def get_weekly_report() -> dict:
    """지난 7일 시장 요약 리포트.

    Returns:
        {
            "top_gainers": [...],   # 급등 TOP 5
            "top_losers": [...],    # 급락 TOP 5
            "surge_count": int,     # 7일간 급등 감지 건수
            "most_surged": [...],   # 가장 많이 급등 감지된 아이템 TOP 3
        }
    """
    from src.market.items import _slug_to_ko, _slug_to_en_name

    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()

    with _get_conn() as conn:
        # 지난 7일 급등 알림 건수 + 최다 급등 아이템
        surge_count_row = conn.execute(
            "SELECT COUNT(*) FROM surge_alert WHERE detected_at >= ?",
            (week_ago,),
        ).fetchone()
        surge_count = surge_count_row[0] if surge_count_row else 0

        most_surged_rows = conn.execute(
            """
            SELECT slug, COUNT(*) AS cnt, AVG(change_pct) AS avg_pct
            FROM surge_alert
            WHERE detected_at >= ? AND rank IS NULL
            GROUP BY slug
            ORDER BY cnt DESC, avg_pct DESC
            LIMIT 3
            """,
            (week_ago,),
        ).fetchall()

        # 7일 변동률 계산 — 각 아이템의 7일 전/현재 가격 비교
        # 서브쿼리로 각 slug별 첫 가격(7일 전)과 최신 가격 집계
        gainers_rows = conn.execute(
            """
            WITH ranked AS (
                SELECT slug,
                       COALESCE(sell_min, avg_price) AS price,
                       scanned_at,
                       ROW_NUMBER() OVER (PARTITION BY slug ORDER BY scanned_at ASC) AS rn_asc,
                       ROW_NUMBER() OVER (PARTITION BY slug ORDER BY scanned_at DESC) AS rn_desc
                FROM price_snapshot
                WHERE rank IS NULL
                  AND scanned_at >= ?
                  AND COALESCE(sell_min, avg_price) IS NOT NULL
                  AND COALESCE(sell_min, avg_price) >= 5
            ),
            first_price AS (SELECT slug, price FROM ranked WHERE rn_asc = 1),
            last_price  AS (SELECT slug, price FROM ranked WHERE rn_desc = 1)
            SELECT f.slug,
                   f.price AS price_start,
                   l.price AS price_now,
                   ROUND((l.price - f.price) * 100.0 / f.price, 1) AS change_pct
            FROM first_price f
            JOIN last_price l ON f.slug = l.slug
            WHERE f.price > 0
            ORDER BY change_pct DESC
            LIMIT 5
            """,
            (week_ago,),
        ).fetchall()

        losers_rows = conn.execute(
            """
            WITH ranked AS (
                SELECT slug,
                       COALESCE(sell_min, avg_price) AS price,
                       scanned_at,
                       ROW_NUMBER() OVER (PARTITION BY slug ORDER BY scanned_at ASC) AS rn_asc,
                       ROW_NUMBER() OVER (PARTITION BY slug ORDER BY scanned_at DESC) AS rn_desc
                FROM price_snapshot
                WHERE rank IS NULL
                  AND scanned_at >= ?
                  AND COALESCE(sell_min, avg_price) IS NOT NULL
                  AND COALESCE(sell_min, avg_price) >= 5
            ),
            first_price AS (SELECT slug, price FROM ranked WHERE rn_asc = 1),
            last_price  AS (SELECT slug, price FROM ranked WHERE rn_desc = 1)
            SELECT f.slug,
                   f.price AS price_start,
                   l.price AS price_now,
                   ROUND((l.price - f.price) * 100.0 / f.price, 1) AS change_pct
            FROM first_price f
            JOIN last_price l ON f.slug = l.slug
            WHERE f.price > 0
            ORDER BY change_pct ASC
            LIMIT 5
            """,
            (week_ago,),
        ).fetchall()

    def _fmt(rows, *, gainers: bool) -> list[dict]:
        result = []
        for r in rows:
            slug, p_start, p_now, pct = r
            if gainers and pct <= 0:
                continue
            if not gainers and pct >= 0:
                continue
            ko = _slug_to_ko.get(slug, "")
            en = _slug_to_en_name.get(slug, slug)
            result.append({
                "slug": slug,
                "name": ko or en,
                "price_start": round(p_start, 0),
                "price_now": round(p_now, 0),
                "change_pct": pct,
            })
        return result

    most_surged = []
    for r in most_surged_rows:
        slug, cnt, avg_pct = r
        ko = _slug_to_ko.get(slug, "")
        en = _slug_to_en_name.get(slug, slug)
        most_surged.append({
            "slug": slug,
            "name": ko or en,
            "surge_count": cnt,
            "avg_change_pct": round(avg_pct, 1),
        })

    return {
        "top_gainers": _fmt(gainers_rows, gainers=True),
        "top_losers": _fmt(losers_rows, gainers=False),
        "surge_count": surge_count,
        "most_surged": most_surged,
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
    }


def backfill_from_statistics(slug: str, stats_48h: list[dict], stats_90d: list[dict]) -> int:
    """warframe.market statistics 데이터로 price_snapshot 백필.

    이미 해당 시각 데이터가 있으면 삽입하지 않음 (중복 방지).
    반환: 삽입된 행 수.
    """
    inserted = 0
    rows = []

    # 48시간치 (시간 단위) — avg_price 사용
    for entry in stats_48h:
        dt = entry.get("datetime", "")
        avg = entry.get("avg_price") or entry.get("wa_price")
        vol = entry.get("volume", 0)
        if dt and avg:
            rows.append((slug, None, None, 0, None, 0, float(avg), vol or 0, dt))

    # 90일치 (일 단위, 48h에 없는 오래된 것만)
    # 48h에 이미 있는 날짜 세트
    h48_dates = {e.get("datetime", "")[:10] for e in stats_48h}
    for entry in stats_90d:
        dt = entry.get("datetime", "")
        if dt[:10] in h48_dates:
            continue  # 48h에 더 정밀한 데이터 있음
        avg = entry.get("avg_price") or entry.get("wa_price")
        vol = entry.get("volume", 0)
        if dt and avg:
            rows.append((slug, None, None, 0, None, 0, float(avg), vol or 0, dt))

    if not rows:
        return 0

    with _get_conn() as conn:
        # 이미 해당 slug의 백필 데이터가 있으면 스킵
        existing = conn.execute(
            "SELECT COUNT(*) FROM price_snapshot WHERE slug = ? AND sell_min IS NULL",
            (slug,),
        ).fetchone()[0]
        if existing > 0:
            return 0  # 이미 백필됨

        conn.executemany(
            "INSERT INTO price_snapshot (slug, rank, sell_min, sell_count, buy_max, buy_count, avg_price, volume, scanned_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        inserted = len(rows)

    return inserted
