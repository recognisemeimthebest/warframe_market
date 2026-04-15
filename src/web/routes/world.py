"""월드 상태 API 라우트."""

import asyncio
import json

from fastapi import APIRouter, Query

from src.market.api import get_item_price
from src.market.items import resolve_item
from src.world.api import (
    get_arbitration,
    get_cycles,
    get_fissures,
    get_invasions,
    get_world_state,
    get_void_trader,
    get_steel_path,
    get_incarnon_rotation,
)

router = APIRouter(prefix="/api", tags=["world"])

_vendors_static: dict | None = None


def _load_vendors_static() -> dict:
    global _vendors_static
    if _vendors_static is None:
        from src.config import DATA_DIR
        path = DATA_DIR / "vendors.json"
        try:
            _vendors_static = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _vendors_static = {"nightwave": {}, "syndicates": []}
    return _vendors_static


@router.get("/world")
async def api_world():
    """월드 상태 전체 (균열+중재+침공+사이클)."""
    return await get_world_state()


@router.get("/world/fissures")
async def api_fissures():
    return {"data": await get_fissures()}


@router.get("/world/arbitration")
async def api_arbitration():
    return {"data": await get_arbitration()}


@router.get("/world/invasions")
async def api_invasions():
    return {"data": await get_invasions()}


@router.get("/world/cycles")
async def api_cycles():
    return {"data": await get_cycles()}


@router.get("/incarnon")
async def api_incarnon(search: str = "", weeks: int = 9):
    """인카논 제네시스 어댑터 주간 로테이션 조회."""
    return await get_incarnon_rotation(search=search, weeks=weeks)


@router.get("/vendors")
async def api_vendors():
    """상인 전체 데이터 (키티어 + 테신 + 나이트웨이브 + 진영)."""
    static = _load_vendors_static()
    baro, steel_path = await asyncio.gather(
        get_void_trader(),
        get_steel_path(),
    )

    if baro.get("active") and baro.get("inventory"):
        async def _enrich_baro(item: dict) -> dict:
            resolved = resolve_item(item["item"])
            if resolved:
                slug, _ = resolved
                try:
                    price = await get_item_price(slug)
                    item["market_sell"] = price.sell_min
                    item["market_buy"] = price.buy_max
                    item["slug"] = slug
                except Exception:
                    pass
            return item

        baro["inventory"] = list(
            await asyncio.gather(*[_enrich_baro(i) for i in baro["inventory"]])
        )

    return {
        "baro": baro,
        "steel_path": steel_path,
        "nightwave": static.get("nightwave", {}),
        "syndicates": static.get("syndicates", []),
    }
