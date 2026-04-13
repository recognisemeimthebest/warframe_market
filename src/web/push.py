"""Web Push 구독 관리 + 알림 전송."""

import json
import logging
import sqlite3
from pathlib import Path

from src.config import DATA_DIR, VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_EMAIL

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "push.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_push_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscription (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL UNIQUE,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
    logger.info("Push DB 초기화")


def save_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO push_subscription (endpoint, p256dh, auth, created_at) VALUES (?, ?, ?, ?)",
            (endpoint, p256dh, auth, now),
        )


def delete_subscription(endpoint: str) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM push_subscription WHERE endpoint = ?", (endpoint,))


def get_all_subscriptions() -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT endpoint, p256dh, auth FROM push_subscription").fetchall()
    return [{"endpoint": r[0], "p256dh": r[1], "auth": r[2]} for r in rows]


async def send_push_all(title: str, body: str, url: str = "/") -> None:
    """모든 구독자에게 푸시 알림 전송."""
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        logger.warning("VAPID 키 미설정 — 푸시 알림 스킵")
        return

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("pywebpush 미설치 — 푸시 알림 스킵")
        return

    subs = get_all_subscriptions()
    if not subs:
        return

    payload = json.dumps({"title": title, "body": body, "url": url})
    vapid_claims = {"sub": f"mailto:{VAPID_EMAIL}"}

    failed = []
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims,
            )
        except WebPushException as e:
            if e.response and e.response.status_code in (404, 410):
                failed.append(sub["endpoint"])
            else:
                logger.warning("푸시 전송 실패: %s", e)

    for ep in failed:
        delete_subscription(ep)
    if subs:
        logger.info("푸시 전송: %d명 / 만료 %d개 제거", len(subs) - len(failed), len(failed))
