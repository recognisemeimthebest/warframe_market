"""모딩 공유 — SQLite DB + 이미지 저장 + CRUD."""

import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "modding.db"
IMAGES_DIR = DATA_DIR / "modding_images"

CATEGORIES = [
    "warframe", "primary", "secondary", "melee",
    "archwing", "necramech", "archgun", "companion",
]

MAX_IMAGES = 5
MAX_MEMO_LENGTH = 1000


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_modding_db() -> None:
    """모딩 공유 DB 테이블 생성."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS modding_share (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                item_name TEXT NOT NULL,
                author TEXT NOT NULL,
                memo TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_modding_cat_item
            ON modding_share (category, item_name)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS modding_image (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                share_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (share_id) REFERENCES modding_share(id) ON DELETE CASCADE
            )
        """)
    logger.info("모딩 공유 DB 초기화: %s", DB_PATH)


@dataclass
class ModdingShare:
    id: int
    category: str
    item_name: str
    author: str
    memo: str
    created_at: str
    images: list[str] = field(default_factory=list)  # 파일명 목록


def create_share(
    category: str,
    item_name: str,
    author: str,
    memo: str = "",
    image_filenames: list[str] | None = None,
) -> int | str:
    """모딩 공유 등록. 성공 시 id 반환, 실패 시 에러 메시지."""
    if category not in CATEGORIES:
        return "유효하지 않은 카테고리입니다."
    if not item_name or len(item_name) > 50:
        return "아이템 이름은 1~50자로 입력해주세요."
    if not author or len(author) > 20:
        return "작성자 이름은 1~20자로 입력해주세요."
    if len(memo) > MAX_MEMO_LENGTH:
        memo = memo[:MAX_MEMO_LENGTH]

    now = datetime.now(timezone.utc).isoformat()

    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO modding_share (category, item_name, author, memo, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (category, item_name.strip(), author.strip(), memo.strip(), now),
        )
        share_id = cursor.lastrowid

        if image_filenames:
            for i, fname in enumerate(image_filenames[:MAX_IMAGES]):
                conn.execute(
                    "INSERT INTO modding_image (share_id, filename, sort_order)"
                    " VALUES (?, ?, ?)",
                    (share_id, fname, i),
                )

    return share_id


def save_image(data: bytes, extension: str = "jpg") -> str:
    """이미지 파일 저장. 생성된 파일명 반환."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{extension}"
    filepath = IMAGES_DIR / filename
    filepath.write_bytes(data)
    return filename


def delete_share(share_id: int, author: str = "", is_admin: bool = False) -> bool:
    """모딩 공유 삭제. 본인 또는 관리자만 가능."""
    with _get_conn() as conn:
        if is_admin:
            # 이미지 파일 삭제
            images = conn.execute(
                "SELECT filename FROM modding_image WHERE share_id = ?",
                (share_id,),
            ).fetchall()
            for (fname,) in images:
                (IMAGES_DIR / fname).unlink(missing_ok=True)

            cursor = conn.execute("DELETE FROM modding_share WHERE id = ?", (share_id,))
        else:
            # 이미지 파일 삭제
            images = conn.execute(
                "SELECT mi.filename FROM modding_image mi"
                " JOIN modding_share ms ON mi.share_id = ms.id"
                " WHERE ms.id = ? AND ms.author = ?",
                (share_id, author),
            ).fetchall()
            for (fname,) in images:
                (IMAGES_DIR / fname).unlink(missing_ok=True)

            cursor = conn.execute(
                "DELETE FROM modding_share WHERE id = ? AND author = ?",
                (share_id, author),
            )
    return cursor.rowcount > 0


def get_shares(category: str = "", item_name: str = "", limit: int = 50) -> list[ModdingShare]:
    """모딩 공유 목록 조회. category 빈 문자열이면 전체 카테고리 조회."""
    with _get_conn() as conn:
        if category and item_name:
            rows = conn.execute(
                "SELECT id, category, item_name, author, memo, created_at"
                " FROM modding_share WHERE category = ? AND item_name = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (category, item_name, limit),
            ).fetchall()
        elif category:
            rows = conn.execute(
                "SELECT id, category, item_name, author, memo, created_at"
                " FROM modding_share WHERE category = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, category, item_name, author, memo, created_at"
                " FROM modding_share ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        shares = []
        for r in rows:
            images = conn.execute(
                "SELECT filename FROM modding_image WHERE share_id = ? ORDER BY sort_order",
                (r[0],),
            ).fetchall()
            shares.append(ModdingShare(
                id=r[0], category=r[1], item_name=r[2],
                author=r[3], memo=r[4] or "", created_at=r[5],
                images=[img[0] for img in images],
            ))

    return shares


def get_items_in_category(category: str) -> list[dict]:
    """카테고리별 공유가 있는 아이템 목록 (건수 포함)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT item_name, COUNT(*) as cnt, MAX(created_at) as latest"
            " FROM modding_share WHERE category = ?"
            " GROUP BY item_name ORDER BY latest DESC",
            (category,),
        ).fetchall()

    return [
        {"item_name": r[0], "count": r[1], "latest": r[2]}
        for r in rows
    ]
