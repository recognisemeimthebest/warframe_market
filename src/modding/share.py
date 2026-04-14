"""모딩 공유 — SQLite DB + 이미지 저장 + CRUD."""

import hashlib
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

SUBTYPES: dict[str, list[str]] = {
    "warframe": [],
    "primary": ["소총", "샷건", "저격총", "활", "런처"],
    "secondary": ["보조무기", "투척"],
    "melee": ["단검", "쌍단검", "검", "쌍검", "대검", "폴암", "해머", "건블레이드", "니카나", "레이피어", "클로", "주먹", "채찍", "톤파", "스태프"],
    "archwing": [],
    "necramech": [],
    "archgun": ["소총", "런처"],
    "companion": ["센티넬", "쿠브로우", "카밧", "MOA", "하운드", "프레데사이트", "불파파일라"],
}

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
                created_at TEXT NOT NULL,
                sub_type TEXT NOT NULL DEFAULT ''
            )
        """)
        # 기존 DB 마이그레이션: sub_type 컬럼 추가
        try:
            conn.execute("ALTER TABLE modding_share ADD COLUMN sub_type TEXT NOT NULL DEFAULT ''")
            logger.info("modding_share: sub_type 컬럼 추가")
        except Exception:
            pass  # 이미 존재
        # 기존 DB 마이그레이션: password_hash 컬럼 추가
        try:
            conn.execute("ALTER TABLE modding_share ADD COLUMN password_hash TEXT")
            logger.info("modding_share: password_hash 컬럼 추가")
        except Exception:
            pass  # 이미 존재
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


def _hash_password(password: str) -> str:
    """비밀번호 SHA-256 해시."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _verify_password(password: str, stored_hash: str | None) -> bool:
    """비밀번호 검증. stored_hash가 None이면 비밀번호 없이 등록된 글 → 통과."""
    if stored_hash is None:
        return True  # 비밀번호 없이 등록된 구 게시글은 그냥 허용
    return _hash_password(password) == stored_hash


@dataclass
class ModdingShare:
    id: int
    category: str
    item_name: str
    author: str
    memo: str
    created_at: str
    sub_type: str = ""
    images: list[str] = field(default_factory=list)  # 파일명 목록
    has_password: bool = False  # 비밀번호 설정 여부 (hash는 외부 노출 안 함)


def create_share(
    category: str,
    item_name: str,
    author: str,
    memo: str = "",
    image_filenames: list[str] | None = None,
    sub_type: str = "",
    password: str = "",
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
    # 유효하지 않은 서브타입은 빈 문자열로
    valid_subtypes = SUBTYPES.get(category, [])
    if sub_type and valid_subtypes and sub_type not in valid_subtypes:
        sub_type = ""

    password_hash = _hash_password(password) if password else None
    now = datetime.now(timezone.utc).isoformat()

    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO modding_share (category, item_name, author, memo, created_at, sub_type, password_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (category, item_name.strip(), author.strip(), memo.strip(), now, sub_type, password_hash),
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


def _check_auth(conn: sqlite3.Connection, share_id: int, author: str, password: str) -> bool:
    """작성자 이름 + 비밀번호 검증. 실패 시 False."""
    row = conn.execute(
        "SELECT author, password_hash FROM modding_share WHERE id = ?", (share_id,)
    ).fetchone()
    if not row:
        return False
    stored_author, stored_hash = row
    if stored_author != author:
        return False
    return _verify_password(password, stored_hash)


def delete_share(share_id: int, author: str = "", password: str = "", is_admin: bool = False) -> bool | str:
    """모딩 공유 삭제. 성공 시 True, 인증 실패 시 에러 메시지."""
    with _get_conn() as conn:
        if is_admin:
            images = conn.execute(
                "SELECT filename FROM modding_image WHERE share_id = ?", (share_id,)
            ).fetchall()
            for (fname,) in images:
                (IMAGES_DIR / fname).unlink(missing_ok=True)
            cursor = conn.execute("DELETE FROM modding_share WHERE id = ?", (share_id,))
        else:
            if not _check_auth(conn, share_id, author, password):
                return "작성자 이름 또는 비밀번호가 올바르지 않습니다."
            images = conn.execute(
                "SELECT mi.filename FROM modding_image mi"
                " JOIN modding_share ms ON mi.share_id = ms.id"
                " WHERE ms.id = ?", (share_id,)
            ).fetchall()
            for (fname,) in images:
                (IMAGES_DIR / fname).unlink(missing_ok=True)
            cursor = conn.execute("DELETE FROM modding_share WHERE id = ?", (share_id,))
    return cursor.rowcount > 0


def update_share(
    share_id: int,
    author: str,
    password: str,
    memo: str,
    image_filenames: list[str] | None = None,
) -> bool | str:
    """모딩 공유 메모+이미지 수정. 성공 시 True, 인증 실패 시 에러 메시지."""
    if len(memo) > MAX_MEMO_LENGTH:
        memo = memo[:MAX_MEMO_LENGTH]
    with _get_conn() as conn:
        if not _check_auth(conn, share_id, author, password):
            return "작성자 이름 또는 비밀번호가 올바르지 않습니다."
        cursor = conn.execute(
            "UPDATE modding_share SET memo = ? WHERE id = ?",
            (memo.strip(), share_id),
        )
        if image_filenames is not None:
            # 기존 이미지 파일명 가져오기
            old_images = conn.execute(
                "SELECT filename FROM modding_image WHERE share_id = ?", (share_id,)
            ).fetchall()
            old_set = {r[0] for r in old_images}
            new_set = set(image_filenames[:MAX_IMAGES])
            # 제거된 이미지 파일 삭제
            for fname in old_set - new_set:
                (IMAGES_DIR / fname).unlink(missing_ok=True)
            # DB 이미지 목록 교체
            conn.execute("DELETE FROM modding_image WHERE share_id = ?", (share_id,))
            for i, fname in enumerate(image_filenames[:MAX_IMAGES]):
                conn.execute(
                    "INSERT INTO modding_image (share_id, filename, sort_order) VALUES (?, ?, ?)",
                    (share_id, fname, i),
                )
    return cursor.rowcount > 0


def get_shares(category: str = "", item_name: str = "", limit: int = 50) -> list[ModdingShare]:
    """모딩 공유 목록 조회. category 빈 문자열이면 전체 카테고리 조회."""
    with _get_conn() as conn:
        if category and item_name:
            rows = conn.execute(
                "SELECT id, category, item_name, author, memo, created_at, sub_type, password_hash"
                " FROM modding_share WHERE category = ? AND item_name = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (category, item_name, limit),
            ).fetchall()
        elif category:
            rows = conn.execute(
                "SELECT id, category, item_name, author, memo, created_at, sub_type, password_hash"
                " FROM modding_share WHERE category = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, category, item_name, author, memo, created_at, sub_type, password_hash"
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
                sub_type=r[6] or "",
                images=[img[0] for img in images],
                has_password=r[7] is not None,
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
