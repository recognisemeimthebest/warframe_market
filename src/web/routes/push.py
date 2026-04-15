"""Web Push API 라우트."""

from fastapi import APIRouter
from pydantic import BaseModel

from src.config import VAPID_PUBLIC_KEY
from src.web.push import delete_subscription, save_subscription

router = APIRouter(prefix="/api/push", tags=["push"])


# ── Pydantic 모델 ──

class PushKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: PushKeys


class UnsubscribeRequest(BaseModel):
    endpoint: str


@router.get("/vapid-public-key")
async def api_vapid_key():
    return {"key": VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def api_push_subscribe(body: SubscribeRequest):
    try:
        save_subscription(
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
        )
        return {"ok": True}
    except Exception:
        return {"ok": False}


@router.post("/unsubscribe")
async def api_push_unsubscribe(body: UnsubscribeRequest):
    delete_subscription(body.endpoint)
    return {"ok": True}
