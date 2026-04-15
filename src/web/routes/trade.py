"""거래소 API 라우트."""

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from src.market.trade import (
    create_listing,
    delete_listing,
    get_listings,
    get_user_by_name,
    register_user,
)

router = APIRouter(prefix="/api/trade", tags=["trade"])


# ── Pydantic 모델 ──

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=20)


class CreateListingRequest(BaseModel):
    user_name: str
    item_slug: str
    item_name: str
    trade_type: Literal["buy", "sell"]
    price: int = Field(..., ge=1)
    rank: int | None = None
    quantity: int = Field(1, ge=1)
    memo: str = Field("", max_length=100)


@router.post("/register")
async def api_trade_register(body: RegisterRequest):
    """거래소 유저 등록 요청."""
    result = register_user(body.name.strip())
    if isinstance(result, str):
        return {"ok": False, "msg": result}
    return {"ok": True, "user": {"id": result.id, "name": result.name, "status": result.status}}


@router.get("/user")
async def api_trade_user(name: str = ""):
    """유저 상태 조회."""
    if not name:
        return {"user": None}
    user = get_user_by_name(name)
    if not user:
        return {"user": None}
    return {"user": {"id": user.id, "name": user.name, "status": user.status}}


@router.get("/listings")
async def api_trade_listings(trade_type: str = "", limit: int = 50):
    """매물 목록."""
    listings = get_listings(trade_type=trade_type, limit=limit)
    return {"data": [
        {
            "id": l.id, "user_name": l.user_name, "trade_type": l.trade_type,
            "item_slug": l.item_slug, "item_name": l.item_name,
            "price": l.price, "rank": l.rank, "quantity": l.quantity,
            "memo": l.memo, "created_at": l.created_at,
        }
        for l in listings
    ]}


@router.post("/listings")
async def api_trade_create_listing(body: CreateListingRequest):
    """매물 등록."""
    user = get_user_by_name(body.user_name.strip())
    if not user or user.status != "approved":
        return {"ok": False, "msg": "승인된 유저만 매물을 등록할 수 있습니다."}

    if not body.item_slug.strip() or not body.item_name.strip():
        return {"ok": False, "msg": "아이템을 선택해주세요."}

    listing_id = create_listing(
        user_id=user.id, trade_type=body.trade_type,
        item_slug=body.item_slug.strip(), item_name=body.item_name.strip(),
        price=body.price, rank=body.rank, quantity=body.quantity, memo=body.memo.strip(),
    )
    return {"ok": True, "id": listing_id}


@router.delete("/listings/{listing_id}")
async def api_trade_delete_listing(listing_id: int, user_name: str = Query("")):
    """매물 삭제 (본인)."""
    if not user_name:
        return {"ok": False, "msg": "유저 이름이 필요합니다."}
    ok = delete_listing(listing_id, user_name=user_name)
    return {"ok": ok, "msg": "" if ok else "삭제 권한이 없거나 존재하지 않는 매물입니다."}
