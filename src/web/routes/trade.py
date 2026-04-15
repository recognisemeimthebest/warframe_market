"""거래소 API 라우트."""

from fastapi import APIRouter, Query

from src.market.trade import (
    create_listing,
    delete_listing,
    get_listings,
    get_user_by_name,
    register_user,
)

router = APIRouter(prefix="/api/trade", tags=["trade"])


@router.post("/register")
async def api_trade_register(body: dict):
    """거래소 유저 등록 요청."""
    name = body.get("name", "").strip()
    if not name or len(name) > 20:
        return {"ok": False, "msg": "이름은 1~20자로 입력해주세요."}
    result = register_user(name)
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
async def api_trade_create_listing(body: dict):
    """매물 등록."""
    user_name = body.get("user_name", "").strip()
    user = get_user_by_name(user_name)
    if not user or user.status != "approved":
        return {"ok": False, "msg": "승인된 유저만 매물을 등록할 수 있습니다."}

    item_slug = body.get("item_slug", "").strip()
    item_name = body.get("item_name", "").strip()
    trade_type = body.get("trade_type", "")
    price = body.get("price", 0)
    rank = body.get("rank")
    quantity = body.get("quantity", 1)
    memo = body.get("memo", "").strip()

    if trade_type not in ("buy", "sell"):
        return {"ok": False, "msg": "trade_type은 buy 또는 sell이어야 합니다."}
    if not item_slug or not item_name:
        return {"ok": False, "msg": "아이템을 선택해주세요."}
    if not isinstance(price, int) or price < 1:
        return {"ok": False, "msg": "가격은 1p 이상이어야 합니다."}
    if not isinstance(quantity, int) or quantity < 1:
        quantity = 1
    if len(memo) > 100:
        memo = memo[:100]

    listing_id = create_listing(
        user_id=user.id, trade_type=trade_type,
        item_slug=item_slug, item_name=item_name,
        price=price, rank=rank, quantity=quantity, memo=memo,
    )
    return {"ok": True, "id": listing_id}


@router.delete("/listings/{listing_id}")
async def api_trade_delete_listing(listing_id: int, user_name: str = Query("")):
    """매물 삭제 (본인)."""
    if not user_name:
        return {"ok": False, "msg": "유저 이름이 필요합니다."}
    ok = delete_listing(listing_id, user_name=user_name)
    return {"ok": ok, "msg": "" if ok else "삭제 권한이 없거나 존재하지 않는 매물입니다."}
