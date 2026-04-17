"""거래소 게시판 (자체 사용자) — SQLite + bcrypt.

게시글 타입: WTB(삽니다) / WTS(팝니다) / RIVEN(리벤)
인증: 회원가입 없음, 게시글 단위 IGN + 비밀번호.
관리자: ADMIN_MASTER_PASSWORD 일치 시 모든 글/문의 삭제 가능.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

import bcrypt

from src.config import ADMIN_MASTER_PASSWORD, DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "board.db"

PostType = Literal["WTB", "WTS", "RIVEN"]
VALID_TYPES: tuple[PostType, ...] = ("WTB", "WTS", "RIVEN")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_board_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS board_post (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK (type IN ('WTB','WTS','RIVEN')),
                item_name TEXT NOT NULL,
                price INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                ign TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS board_riven (
                post_id INTEGER PRIMARY KEY,
                weapon_name TEXT NOT NULL,
                polarity TEXT NOT NULL DEFAULT '',
                mastery_rank INTEGER NOT NULL DEFAULT 8,
                rolls INTEGER NOT NULL DEFAULT 0,
                stats_json TEXT NOT NULL DEFAULT '[]',
                negative_stat TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (post_id) REFERENCES board_post(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS board_contact (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                from_ign TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (post_id) REFERENCES board_post(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_board_post_type ON board_post(type, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_board_post_ign ON board_post(ign)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_board_contact_post ON board_contact(post_id, is_read)")
    logger.info("Board DB 초기화: %s", DB_PATH)


# ── 비밀번호 ──

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _is_master(password: str) -> bool:
    return bool(ADMIN_MASTER_PASSWORD) and password == ADMIN_MASTER_PASSWORD


# ── 데이터 클래스 ──

@dataclass
class Post:
    id: int
    type: str
    item_name: str
    price: int
    quantity: int
    ign: str
    note: str
    created_at: str
    updated_at: str
    riven: Optional[dict] = None
    contact_count: int = 0
    unread_count: int = 0


@dataclass
class Contact:
    id: int
    post_id: int
    from_ign: str
    message: str
    created_at: str
    is_read: bool


# ── CRUD ──

def create_post(
    *,
    type: str,
    item_name: str,
    price: int,
    quantity: int,
    ign: str,
    password: str,
    note: str,
    riven: Optional[dict] = None,
) -> int:
    """게시글 생성. 리벤 타입이면 riven dict 필수."""
    if type not in VALID_TYPES:
        raise ValueError(f"잘못된 타입: {type}")
    if not ign.strip() or not password:
        raise ValueError("IGN과 비밀번호는 필수입니다.")

    now = _now()
    pwd_hash = _hash_password(password)

    with _get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO board_post
               (type, item_name, price, quantity, ign, password_hash, note, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (type, item_name.strip(), int(price), int(quantity), ign.strip(),
             pwd_hash, note.strip(), now, now),
        )
        post_id = cur.lastrowid

        if type == "RIVEN":
            r = riven or {}
            stats_json = json.dumps(r.get("stats", []), ensure_ascii=False)
            conn.execute(
                """INSERT INTO board_riven
                   (post_id, weapon_name, polarity, mastery_rank, rolls, stats_json, negative_stat)
                   VALUES (?,?,?,?,?,?,?)""",
                (post_id, str(r.get("weapon_name", "")).strip(),
                 str(r.get("polarity", "")).strip(),
                 int(r.get("mastery_rank", 8)),
                 int(r.get("rolls", 0)),
                 stats_json,
                 str(r.get("negative_stat", "")).strip()),
            )

    return post_id


def _row_to_post(row: sqlite3.Row, riven_row: Optional[sqlite3.Row] = None,
                 contact_count: int = 0, unread_count: int = 0) -> Post:
    riven_data = None
    if riven_row is not None:
        try:
            stats = json.loads(riven_row["stats_json"])
        except json.JSONDecodeError:
            stats = []
        riven_data = {
            "weapon_name": riven_row["weapon_name"],
            "polarity": riven_row["polarity"],
            "mastery_rank": riven_row["mastery_rank"],
            "rolls": riven_row["rolls"],
            "stats": stats,
            "negative_stat": riven_row["negative_stat"],
        }
    return Post(
        id=row["id"], type=row["type"], item_name=row["item_name"],
        price=row["price"], quantity=row["quantity"], ign=row["ign"],
        note=row["note"], created_at=row["created_at"], updated_at=row["updated_at"],
        riven=riven_data, contact_count=contact_count, unread_count=unread_count,
    )


def list_posts(type: Optional[str] = None, limit: int = 100) -> list[Post]:
    """게시글 목록. type 필터 가능."""
    with _get_conn() as conn:
        if type and type in VALID_TYPES:
            rows = conn.execute(
                "SELECT * FROM board_post WHERE type = ? ORDER BY created_at DESC LIMIT ?",
                (type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM board_post ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        riven_rows: dict[int, sqlite3.Row] = {}
        riven_ids = [r["id"] for r in rows if r["type"] == "RIVEN"]
        if riven_ids:
            placeholders = ",".join("?" * len(riven_ids))
            for rr in conn.execute(
                f"SELECT * FROM board_riven WHERE post_id IN ({placeholders})",
                riven_ids,
            ).fetchall():
                riven_rows[rr["post_id"]] = rr

        counts: dict[int, tuple[int, int]] = {}
        if rows:
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))
            for cr in conn.execute(
                f"""SELECT post_id, COUNT(*) AS total,
                           SUM(CASE WHEN is_read=0 THEN 1 ELSE 0 END) AS unread
                    FROM board_contact WHERE post_id IN ({placeholders}) GROUP BY post_id""",
                ids,
            ).fetchall():
                counts[cr["post_id"]] = (cr["total"] or 0, cr["unread"] or 0)

    return [
        _row_to_post(
            r,
            riven_rows.get(r["id"]),
            counts.get(r["id"], (0, 0))[0],
            counts.get(r["id"], (0, 0))[1],
        )
        for r in rows
    ]


def get_post(post_id: int) -> Optional[Post]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM board_post WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return None
        riven_row = None
        if row["type"] == "RIVEN":
            riven_row = conn.execute(
                "SELECT * FROM board_riven WHERE post_id = ?", (post_id,)
            ).fetchone()
        cr = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN is_read=0 THEN 1 ELSE 0 END) AS unread
               FROM board_contact WHERE post_id = ?""",
            (post_id,),
        ).fetchone()
    total = (cr["total"] or 0) if cr else 0
    unread = (cr["unread"] or 0) if cr else 0
    return _row_to_post(row, riven_row, total, unread)


def update_post(
    post_id: int,
    password: str,
    *,
    item_name: Optional[str] = None,
    price: Optional[int] = None,
    quantity: Optional[int] = None,
    note: Optional[str] = None,
    riven: Optional[dict] = None,
) -> tuple[bool, str]:
    """비밀번호 검증 후 수정. (성공, 메시지) 반환."""
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM board_post WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return False, "게시글이 존재하지 않습니다."

        if not (_is_master(password) or _verify_password(password, row["password_hash"])):
            return False, "비밀번호가 일치하지 않습니다."

        fields, values = [], []
        if item_name is not None:
            fields.append("item_name = ?"); values.append(item_name.strip())
        if price is not None:
            fields.append("price = ?"); values.append(int(price))
        if quantity is not None:
            fields.append("quantity = ?"); values.append(int(quantity))
        if note is not None:
            fields.append("note = ?"); values.append(note.strip())

        if fields:
            fields.append("updated_at = ?"); values.append(_now())
            values.append(post_id)
            conn.execute(f"UPDATE board_post SET {', '.join(fields)} WHERE id = ?", values)

        if row["type"] == "RIVEN" and riven is not None:
            stats_json = json.dumps(riven.get("stats", []), ensure_ascii=False)
            conn.execute(
                """UPDATE board_riven SET weapon_name=?, polarity=?, mastery_rank=?,
                   rolls=?, stats_json=?, negative_stat=? WHERE post_id=?""",
                (str(riven.get("weapon_name", "")).strip(),
                 str(riven.get("polarity", "")).strip(),
                 int(riven.get("mastery_rank", 8)),
                 int(riven.get("rolls", 0)),
                 stats_json,
                 str(riven.get("negative_stat", "")).strip(),
                 post_id),
            )

    return True, "수정 완료."


def delete_post(post_id: int, password: str) -> tuple[bool, str]:
    """비밀번호(또는 마스터) 일치 시 삭제."""
    with _get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM board_post WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return False, "게시글이 존재하지 않습니다."
        if not (_is_master(password) or _verify_password(password, row["password_hash"])):
            return False, "비밀번호가 일치하지 않습니다."
        conn.execute("DELETE FROM board_post WHERE id = ?", (post_id,))
    return True, "삭제 완료."


# ── 문의(연락) ──

def add_contact(post_id: int, from_ign: str, message: str) -> tuple[bool, str, Optional[Post]]:
    """게시글에 구매/판매 문의 추가. (성공, 메시지, 대상 게시글) 반환."""
    if not from_ign.strip():
        return False, "본인 IGN을 입력해주세요.", None
    post = get_post(post_id)
    if not post:
        return False, "게시글이 존재하지 않습니다.", None
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO board_contact (post_id, from_ign, message, created_at) VALUES (?,?,?,?)",
            (post_id, from_ign.strip(), message.strip()[:200], _now()),
        )
    return True, "문의 등록 완료.", post


def list_my_posts(ign: str, password: str) -> tuple[bool, str, list[Post]]:
    """IGN+비밀번호 검증 → 본인 게시글 목록.

    한 IGN의 어떤 게시글이라도 비번이 일치하면 그 IGN 명의 게시글 전부 반환.
    """
    ign = ign.strip()
    if not ign or not password:
        return False, "IGN과 비밀번호를 입력해주세요.", []
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM board_post WHERE ign = ? ORDER BY created_at DESC",
            (ign,),
        ).fetchall()
        if not rows:
            return False, "해당 IGN의 게시글이 없습니다.", []

        if not _is_master(password):
            verified = any(_verify_password(password, r["password_hash"]) for r in rows)
            if not verified:
                return False, "비밀번호가 일치하지 않습니다.", []

        riven_rows: dict[int, sqlite3.Row] = {}
        riven_ids = [r["id"] for r in rows if r["type"] == "RIVEN"]
        if riven_ids:
            placeholders = ",".join("?" * len(riven_ids))
            for rr in conn.execute(
                f"SELECT * FROM board_riven WHERE post_id IN ({placeholders})",
                riven_ids,
            ).fetchall():
                riven_rows[rr["post_id"]] = rr

        counts: dict[int, tuple[int, int]] = {}
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        for cr in conn.execute(
            f"""SELECT post_id, COUNT(*) AS total,
                       SUM(CASE WHEN is_read=0 THEN 1 ELSE 0 END) AS unread
                FROM board_contact WHERE post_id IN ({placeholders}) GROUP BY post_id""",
            ids,
        ).fetchall():
            counts[cr["post_id"]] = (cr["total"] or 0, cr["unread"] or 0)

    posts = [
        _row_to_post(
            r,
            riven_rows.get(r["id"]),
            counts.get(r["id"], (0, 0))[0],
            counts.get(r["id"], (0, 0))[1],
        )
        for r in rows
    ]
    return True, "", posts


def list_contacts(post_id: int, password: str) -> tuple[bool, str, list[Contact]]:
    """게시글의 문의 목록 (작성자 비번 또는 마스터)."""
    with _get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM board_post WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return False, "게시글이 존재하지 않습니다.", []
        if not (_is_master(password) or _verify_password(password, row["password_hash"])):
            return False, "비밀번호가 일치하지 않습니다.", []
        rows = conn.execute(
            "SELECT * FROM board_contact WHERE post_id = ? ORDER BY created_at DESC",
            (post_id,),
        ).fetchall()
    contacts = [
        Contact(
            id=r["id"], post_id=r["post_id"], from_ign=r["from_ign"],
            message=r["message"], created_at=r["created_at"], is_read=bool(r["is_read"]),
        )
        for r in rows
    ]
    return True, "", contacts


def mark_contacts_read(post_id: int, password: str) -> tuple[bool, str]:
    with _get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM board_post WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return False, "게시글이 존재하지 않습니다."
        if not (_is_master(password) or _verify_password(password, row["password_hash"])):
            return False, "비밀번호가 일치하지 않습니다."
        conn.execute("UPDATE board_contact SET is_read = 1 WHERE post_id = ?", (post_id,))
    return True, "확인 완료."
