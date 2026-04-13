"""REST API 라우트."""

from fastapi import APIRouter

from src.market.api import get_item_price
from src.market.items import resolve_item

router = APIRouter(prefix="/api")


@router.get("/price/{query}")
async def price(query: str):
    """아이템 시세 조회 REST API."""
    result = resolve_item(query)
    if not result:
        return {"error": True, "message": f'"{query}" 아이템을 찾을 수 없습니다.'}

    slug, display_name = result
    item_price = await get_item_price(slug, display_name)
    if not item_price:
        return {"error": True, "message": "시세 정보를 가져올 수 없습니다."}

    return {
        "error": False,
        "item_name": item_price.item_name,
        "slug": item_price.slug,
        "sell_min": item_price.sell_min,
        "sell_count": item_price.sell_count,
        "buy_max": item_price.buy_max,
        "buy_count": item_price.buy_count,
        "avg_48h": item_price.avg_48h,
        "volume_48h": item_price.volume_48h,
    }
