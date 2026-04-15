"""사용자 선택 기반 학습 별명 DB.

사용자가 suggest 카드에서 아이템을 선택하면
(원래 쿼리 → slug) 매핑을 저장해두고 이후 검색에 활용한다.
"""

import logging
import sqlite3
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

_DB_PATH = DATA_DIR / "learned_aliases.db"

# 메모리 캐시: query_normalized → slug
_cache: dict[str, str] = {}


def _normalize(query: str) -> str:
    return query.strip().lower().replace(" ", "")


def init_aliases_db() -> None:
    """DB 테이블 생성 + 메모리 캐시 로드."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learned_aliases (
                query_normalized TEXT PRIMARY KEY,
                query_original   TEXT NOT NULL,
                slug             TEXT NOT NULL,
                hit_count        INTEGER NOT NULL DEFAULT 1,
                updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        _load_cache(conn)
    finally:
        conn.close()
    logger.info("학습 별명 DB 로드: %d개", len(_cache))


def _load_cache(conn: sqlite3.Connection) -> None:
    _cache.clear()
    for row in conn.execute("SELECT query_normalized, slug FROM learned_aliases"):
        _cache[row[0]] = row[1]


def save_alias(query: str, slug: str) -> None:
    """쿼리 → slug 매핑 저장 (이미 있으면 hit_count 증가)."""
    key = _normalize(query)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute("""
            INSERT INTO learned_aliases (query_normalized, query_original, slug, hit_count, updated_at)
            VALUES (?, ?, ?, 1, datetime('now'))
            ON CONFLICT(query_normalized) DO UPDATE SET
                slug       = excluded.slug,
                hit_count  = hit_count + 1,
                updated_at = datetime('now')
        """, (key, query.strip(), slug))
        conn.commit()
        _cache[key] = slug
        logger.info("학습 별명 저장: '%s' → %s", query, slug)
    except Exception:
        logger.exception("학습 별명 저장 실패")
    finally:
        conn.close()


def lookup_alias(query: str) -> str | None:
    """메모리 캐시에서 slug 반환. 없으면 None."""
    return _cache.get(_normalize(query))


def list_aliases(limit: int = 200) -> list[dict]:
    """저장된 별명 목록 반환 (관리용)."""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT query_original, slug, hit_count, updated_at FROM learned_aliases ORDER BY hit_count DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_alias(query: str) -> bool:
    """잘못 학습된 별명 삭제."""
    key = _normalize(query)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.execute("DELETE FROM learned_aliases WHERE query_normalized = ?", (key,))
        conn.commit()
        _cache.pop(key, None)
        return cur.rowcount > 0
    finally:
        conn.close()
