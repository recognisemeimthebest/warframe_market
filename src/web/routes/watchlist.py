"""워치리스트 API 라우트."""

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from src.market.api import get_item_price
from src.market.watchlist import (
    add_watch,
    get_user_watches,
    remove_watch,
    update_watch_price,
)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


# ── Pydantic 모델 ──

class AddWatchRequest(BaseModel):
    user_name: str
    item_slug: str
    item_name: str
    target_price: int = Field(..., ge=1)


@router.get("")
async def api_watchlist(user_name: str = ""):
    """유저 워치리스트."""
    if not user_name:
        return {"data": []}
    watches = get_user_watches(user_name)
    return {"data": [
        {
            "id": w.id, "item_slug": w.item_slug, "item_name": w.item_name,
            "target_price": w.target_price, "current_price": w.current_price,
            "status": w.status, "created_at": w.created_at,
        }
        for w in watches
    ]}


@router.post("")
async def api_add_watch(body: AddWatchRequest):
    """워치리스트 추가."""
    slug = body.item_slug.strip()
    result = add_watch(
        user_name=body.user_name.strip(),
        item_slug=slug,
        item_name=body.item_name.strip(),
        target_price=body.target_price,
    )
    if isinstance(result, str):
        return {"ok": False, "msg": result}
    try:
        price = await get_item_price(slug)
        if price and price.sell_min is not None:
            update_watch_price(result, price.sell_min)
    except Exception:
        pass
    return {"ok": True, "id": result}


@router.delete("/{watch_id}")
async def api_remove_watch(watch_id: int, user_name: str = Query("")):
    """워치리스트 삭제."""
    ok = remove_watch(watch_id, user_name)
    return {"ok": ok}
