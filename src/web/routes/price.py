"""REST API 라우트 — 시세 조회, 추세, 주간 리포트."""

from fastapi import APIRouter, Body

from src.market.api import get_item_price
from src.market.history import get_alert_config, get_price_trend, get_weekly_report, save_alert_config
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

    # 가격 추세 포함
    trend = get_price_trend(slug)

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
        "vaulted": item_price.vaulted,
        "trend": trend,
    }


@router.get("/alert-config")
async def get_alert_config_api():
    """알림 기준 설정 조회."""
    return get_alert_config()


@router.post("/alert-config")
async def save_alert_config_api(body: dict = Body(...)):
    """알림 기준 설정 저장."""
    allowed = {"threshold_1d", "threshold_7d", "threshold_30d", "min_price"}
    filtered = {k: v for k, v in body.items() if k in allowed}
    if not filtered:
        return {"error": True, "message": "유효한 설정값이 없습니다."}
    try:
        save_alert_config(filtered)
        return {"error": False, "saved": filtered}
    except Exception as e:
        return {"error": True, "message": str(e)}


@router.get("/trend/{query}")
async def trend(query: str):
    """아이템 가격 추세 조회."""
    result = resolve_item(query)
    if not result:
        return {"error": True, "message": f'"{query}" 아이템을 찾을 수 없습니다.'}
    slug, _ = result
    t = get_price_trend(slug)
    if not t:
        return {"error": True, "message": "추세 데이터가 부족합니다. (최소 2일치 필요)"}
    return {"error": False, "slug": slug, **t}


@router.get("/report/weekly")
async def weekly_report():
    """주간 시장 리포트."""
    return get_weekly_report()
