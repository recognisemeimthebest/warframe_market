"""관리자 API 라우트."""

from fastapi import APIRouter, Query

from src.analytics import get_summary
from src.market.learned_aliases import delete_alias, list_aliases
from src.market.trade import (
    approve_user,
    delete_listing,
    list_users,
    revoke_user,
)
from src.modding.share import delete_share, get_shares

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def api_admin_users():
    users = list_users()
    return {"data": [{"id": u.id, "name": u.name, "status": u.status, "created_at": u.created_at} for u in users]}


@router.post("/users/{name}/approve")
async def api_admin_approve(name: str):
    ok = approve_user(name)
    return {"ok": ok}


@router.post("/users/{name}/revoke")
async def api_admin_revoke(name: str):
    ok = revoke_user(name)
    return {"ok": ok}


@router.delete("/trade/{listing_id}")
async def api_admin_delete_listing(listing_id: int):
    ok = delete_listing(listing_id, is_admin=True)
    return {"ok": ok}


@router.get("/modding")
async def api_admin_modding():
    shares = get_shares(category="", limit=200)
    return {"data": [
        {
            "id": s.id, "category": s.category, "item_name": s.item_name,
            "author": s.author, "memo": s.memo, "created_at": s.created_at,
            "images": [f"/api/modding/images/{fname}" for fname in s.images],
        }
        for s in shares
    ]}


@router.delete("/modding/{share_id}")
async def api_admin_delete_share(share_id: int):
    ok = delete_share(share_id, is_admin=True)
    return {"ok": ok}


@router.get("/aliases")
async def api_admin_aliases():
    """학습된 별명 목록."""
    return {"data": list_aliases()}


@router.delete("/aliases")
async def api_admin_delete_alias(query: str = Query("")):
    """잘못 학습된 별명 삭제."""
    if not query:
        return {"ok": False}
    ok = delete_alias(query)
    return {"ok": ok}


@router.get("/analytics")
async def api_admin_analytics(days: int = 7):
    """기능별 사용 통계 요약."""
    return get_summary(days)
