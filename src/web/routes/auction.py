"""경매 API 라우트 — 리벤 모드 + 리치/시스터."""

import asyncio

from fastapi import APIRouter

from src.market.auction import (
    get_lich_items,
    get_riven_items,
    resolve_riven_weapon,
    search_lich_auctions,
    search_riven_auctions,
)

router = APIRouter(prefix="/api/auction", tags=["auction"])

_POPULAR_RIVEN_BY_GROUP = {
    "primary": ["rubico", "ignis", "acceltra", "soma", "stahlta", "kuva_chakkhurr", "zarr", "tiberon"],
    "secondary": ["catchmoon", "sporelacer", "tombfinger", "pyrana", "epitaph", "nukor", "staticor", "atomos"],
    "melee": ["gram", "stropha", "nikana", "kronen", "orthos", "reaper_prime", "venka", "lesion"],
    "kitgun": ["catchmoon", "sporelacer", "tombfinger", "gaze", "vermisplicer", "rattleguts"],
    "zaw": ["plague_kripath", "plague_keewar", "sepfahn", "cyath", "balla", "dokrahm"],
    "archgun": ["mausolon", "kuva_ayanga", "grattler", "fluctus", "imperator"],
    "sentinel": ["vulklok", "deth_machine_rifle", "sweeper", "stinger", "laser_rifle"],
}
_POPULAR_RIVEN_MIX = [
    "rubico", "ignis", "acceltra",
    "catchmoon", "sporelacer", "nukor",
    "gram", "stropha", "nikana",
    "plague_kripath",
]
_POPULAR_LICH_WEAPONS = [
    "kuva_zarr", "kuva_bramma", "kuva_nukor", "tenet_arca_plasmor",
    "tenet_envoy", "kuva_hek", "tenet_cycron",
]


@router.get("/riven")
async def api_riven_auctions(
    weapon: str = "",
    group: str = "",
    buyout_policy: str = "",
    sort_by: str = "price_asc",
    limit: int = 50,
):
    """리벤 경매 검색."""
    bp = buyout_policy if buyout_policy else None
    cap = min(limit, 300)

    if weapon:
        resolved = await resolve_riven_weapon(weapon)
        items = await search_riven_auctions(
            weapon_url_name=resolved,
            buyout_policy=bp,
            sort_by=sort_by,
            limit=cap,
        )
    else:
        popular = _POPULAR_RIVEN_BY_GROUP.get(group, _POPULAR_RIVEN_MIX)
        per = max(4, cap // len(popular))
        tasks = [
            search_riven_auctions(
                weapon_url_name=w,
                buyout_policy=bp,
                sort_by=sort_by,
                limit=per,
            )
            for w in popular
        ]
        results = await asyncio.gather(*tasks)
        items = [item for batch in results for item in batch][:cap]

    return {"data": items}


@router.get("/lich")
async def api_lich_auctions(
    weapon: str = "",
    element: str = "",
    ephemera: str = "",
    buyout_policy: str = "",
    sort_by: str = "price_asc",
    limit: int = 50,
):
    """리치/시스터 경매 검색."""
    eph = None
    if ephemera == "yes":
        eph = True
    elif ephemera == "no":
        eph = False

    bp = buyout_policy if buyout_policy else None
    cap = min(limit, 300)

    if weapon:
        items = await search_lich_auctions(
            weapon_url_name=weapon,
            element=element,
            ephemera=eph,
            buyout_policy=bp,
            sort_by=sort_by,
            limit=cap,
        )
    else:
        per = max(4, cap // len(_POPULAR_LICH_WEAPONS))
        tasks = [
            search_lich_auctions(
                weapon_url_name=w,
                element=element,
                ephemera=eph,
                buyout_policy=bp,
                sort_by=sort_by,
                limit=per,
            )
            for w in _POPULAR_LICH_WEAPONS
        ]
        results = await asyncio.gather(*tasks)
        items = [item for batch in results for item in batch][:cap]

    return {"data": items}


@router.get("/riven/items")
async def api_riven_items():
    """리벤 무기 목록 (자동완성)."""
    return {"data": await get_riven_items()}


@router.get("/lich/items")
async def api_lich_items():
    """리치/시스터 무기 목록."""
    return {"data": await get_lich_items()}
