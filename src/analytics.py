"""사용자 기능 사용 로그 (SQLite)."""

import logging
import sqlite3
import time
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "analytics.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_analytics_db() -> None:
    """DB 테이블 생성."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                ts    INTEGER NOT NULL,
                feature TEXT NOT NULL,
                query TEXT,
                hit   INTEGER DEFAULT 1
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_feature ON usage_log (feature)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_log (ts)")


def log_event(feature: str, query: str = "", hit: bool = True) -> None:
    """기능 사용 이벤트 기록.

    Args:
        feature: 기능명 (예: price_query, farming_search, relic_calc)
        query:   검색어 또는 입력값 (없으면 빈 문자열)
        hit:     결과가 있었는지 여부 (True=성공, False=미스)
    """
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO usage_log (ts, feature, query, hit) VALUES (?, ?, ?, ?)",
                (int(time.time()), feature, query or "", 1 if hit else 0),
            )
    except Exception:
        logger.exception("analytics log 실패")


def get_summary(days: int = 7) -> dict:
    """최근 N일 기능별 사용 통계 요약."""
    since = int(time.time()) - days * 86400
    try:
        with _get_conn() as conn:
            # 기능별 호출 수 + 성공률
            rows = conn.execute("""
                SELECT feature,
                       COUNT(*) AS total,
                       SUM(hit)  AS hits
                FROM usage_log
                WHERE ts >= ?
                GROUP BY feature
                ORDER BY total DESC
            """, (since,)).fetchall()

            # 인기 검색어 TOP 20
            top_queries = conn.execute("""
                SELECT query, COUNT(*) AS cnt
                FROM usage_log
                WHERE ts >= ? AND query != '' AND hit = 1
                GROUP BY query
                ORDER BY cnt DESC
                LIMIT 20
            """, (since,)).fetchall()

        return {
            "days": days,
            "features": [
                {"feature": r[0], "total": r[1], "hit_rate": round(r[2] / r[1], 2) if r[1] else 0}
                for r in rows
            ],
            "top_queries": [{"query": r[0], "count": r[1]} for r in top_queries],
        }
    except Exception:
        logger.exception("analytics summary 실패")
        return {"days": days, "features": [], "top_queries": []}
