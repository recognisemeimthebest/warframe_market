"""Web Push API 라우트."""

from fastapi import APIRouter

from src.config import VAPID_PUBLIC_KEY
from src.web.push import delete_subscription, save_subscription

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get("/vapid-public-key")
async def api_vapid_key():
    return {"key": VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def api_push_subscribe(body: dict):
    try:
        save_subscription(
            endpoint=body["endpoint"],
            p256dh=body["keys"]["p256dh"],
            auth=body["keys"]["auth"],
        )
        return {"ok": True}
    except Exception:
        return {"ok": False}


@router.post("/unsubscribe")
async def api_push_unsubscribe(body: dict):
    delete_subscription(body.get("endpoint", ""))
    return {"ok": True}
