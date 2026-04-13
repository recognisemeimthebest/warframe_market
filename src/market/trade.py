"""커뮤니티 거래소 — 유저 등록 + 매물 관리 (SQLite)."""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "trade.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_trade_db() -> None:
    """거래소 DB 테이블 생성."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_listing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                trade_type TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                item_name TEXT NOT NULL,
                price INTEGER NOT NULL,
                rank INTEGER,
                quantity INTEGER NOT NULL DEFAULT 1,
                memo TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES trade_user(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listing_type
            ON trade_listing (trade_type, created_at DESC)
        """)
    logger.info("거래소 DB 초기화: %s", DB_PATH)


# ── 유저 관리 ──

@dataclass
class TradeUser:
    id: int
    name: str
    status: str  # pending, approved, rejected
    created_at: str


def register_user(name: str) -> TradeUser | str:
    """유저 등록 요청. 이미 존재하면 에러 메시지 반환."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO trade_user (name, status, created_at) VALUES (?, 'pending', ?)",
                (name, now),
            )
            row = conn.execute(
                "SELECT id, name, status, created_at FROM trade_user WHERE name = ?",
                (name,),
            ).fetchone()
        return TradeUser(id=row[0], name=row[1], status=row[2], created_at=row[3])
    except sqlite3.IntegrityError:
        # 이미 존재
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT id, name, status, created_at FROM trade_user WHERE name = ?",
                (name,),
            ).fetchone()
        if row:
            user = TradeUser(id=row[0], name=row[1], status=row[2], created_at=row[3])
            if user.status == "pending":
                return "이미 등록 요청 중입니다. 관리자 승인을 기다려주세요."
            elif user.status == "approved":
                return user  # 이미 승인됨
            else:
                return "등록이 거절되었습니다. 관리자에게 문의하세요."
        return "등록 처리 중 오류가 발생했습니다."


def get_user_by_name(name: str) -> TradeUser | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, status, created_at FROM trade_user WHERE name = ?",
            (name,),
        ).fetchone()
    if not row:
        return None
    return TradeUser(id=row[0], name=row[1], status=row[2], created_at=row[3])


def approve_user(name: str) -> bool:
    """유저 승인."""
    with _get_conn() as conn:
        cursor = conn.execute(
            "UPDATE trade_user SET status = 'approved' WHERE name = ? AND status = 'pending'",
            (name,),
        )
    return cursor.rowcount > 0


def reject_user(name: str) -> bool:
    """유저 거절."""
    with _get_conn() as conn:
        cursor = conn.execute(
            "UPDATE trade_user SET status = 'rejected' WHERE name = ? AND status = 'pending'",
            (name,),
        )
    return cursor.rowcount > 0


def revoke_user(name: str) -> bool:
    """승인된 유저 취소 → pending으로 되돌림."""
    with _get_conn() as conn:
        cursor = conn.execute(
            "UPDATE trade_user SET status = 'pending' WHERE name = ? AND status = 'approved'",
            (name,),
        )
    return cursor.rowcount > 0


def list_users(status: str = "") -> list[TradeUser]:
    """유저 목록 조회."""
    with _get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT id, name, status, created_at FROM trade_user WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, status, created_at FROM trade_user ORDER BY created_at DESC",
            ).fetchall()
    return [TradeUser(id=r[0], name=r[1], status=r[2], created_at=r[3]) for r in rows]


# ── 매물 관리 ──

@dataclass
class TradeListing:
    id: int
    user_name: str
    trade_type: str  # "buy" or "sell"
    item_slug: str
    item_name: str
    price: int
    rank: int | None
    quantity: int
    memo: str
    created_at: str


def create_listing(
    user_id: int,
    trade_type: str,
    item_slug: str,
    item_name: str,
    price: int,
    rank: int | None = None,
    quantity: int = 1,
    memo: str = "",
) -> int:
    """매물 등록. 생성된 listing id 반환."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO trade_listing (user_id, trade_type, item_slug, item_name, price, rank, quantity, memo, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, trade_type, item_slug, item_name, price, rank, quantity, memo, now),
        )
        return cursor.lastrowid


def delete_listing(listing_id: int, user_name: str = "", is_admin: bool = False) -> bool:
    """매물 삭제. 본인 또는 관리자만 가능."""
    with _get_conn() as conn:
        if is_admin:
            cursor = conn.execute("DELETE FROM trade_listing WHERE id = ?", (listing_id,))
        else:
            cursor = conn.execute(
                "DELETE FROM trade_listing WHERE id = ? AND user_id = ("
                "  SELECT id FROM trade_user WHERE name = ?"
                ")",
                (listing_id, user_name),
            )
    return cursor.rowcount > 0


def get_listings(trade_type: str = "", limit: int = 50) -> list[TradeListing]:
    """매물 목록 조회."""
    with _get_conn() as conn:
        if trade_type:
            rows = conn.execute(
                "SELECT l.id, u.name, l.trade_type, l.item_slug, l.item_name,"
                " l.price, l.rank, l.quantity, l.memo, l.created_at"
                " FROM trade_listing l JOIN trade_user u ON l.user_id = u.id"
                " WHERE l.trade_type = ?"
                " ORDER BY l.created_at DESC LIMIT ?",
                (trade_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT l.id, u.name, l.trade_type, l.item_slug, l.item_name,"
                " l.price, l.rank, l.quantity, l.memo, l.created_at"
                " FROM trade_listing l JOIN trade_user u ON l.user_id = u.id"
                " ORDER BY l.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [
        TradeListing(
            id=r[0], user_name=r[1], trade_type=r[2], item_slug=r[3],
            item_name=r[4], price=r[5], rank=r[6], quantity=r[7],
            memo=r[8] or "", created_at=r[9],
        )
        for r in rows
    ]
