"""가상 모딩 계산기 API 라우트."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.wiki.calc import (
    ARCHON_SHARDS,
    calc_warframe_stats,
    calc_weapon_stats,
    get_warframe_grouped_list,
    search_arcanes,
    search_mods,
    search_warframes,
    search_weapon_mods,
    search_weapons,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calc", tags=["calc"])


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class ModSlot(BaseModel):
    name: str
    effects: dict[str, float]
    rank: int
    fusionLimit: int


class ShardSlot(BaseModel):
    color: str
    option_key: str
    tauforged: bool = False


class ArcaneSlot(BaseModel):
    name: str
    effects: dict[str, float]


class ComputeRequest(BaseModel):
    base: dict  # {health, shield, armor, power, sprintSpeed}
    mods: list[ModSlot] = []
    shards: list[ShardSlot] = []
    arcanes: list[ArcaneSlot] = []


class WeaponComputeRequest(BaseModel):
    base: dict  # weapon base stats
    mods: list[ModSlot] = []


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("/warframes")
async def api_search_warframes(q: str = Query(default="", alias="q")):
    """워프레임 이름 검색.

    쿼리 없음 → 드롭다운용 그룹화 목록 (한글명 + 프라임 여부 포함)
    쿼리 있음 → 일반 검색 결과 (상위 10개)

    ``GET /api/calc/warframes?q=라이노``
    """
    try:
        if not q.strip():
            items = await get_warframe_grouped_list()
            return {"ok": True, "items": items, "grouped": True}
        items = await search_warframes(q.strip(), limit=10)
        return {"ok": True, "items": items, "grouped": False}
    except Exception as exc:
        logger.error("워프레임 검색 오류: %s", exc, exc_info=True)
        return {"ok": False, "msg": f"검색 중 오류가 발생했습니다: {exc}"}


@router.get("/mods")
async def api_search_mods(
    q: str = Query(default="", alias="q"),
    compat: str = Query(default="WARFRAME"),
):
    """모드 이름 검색.

    ``GET /api/calc/mods?q=인텐시파이&compat=WARFRAME``
    """
    try:
        items = await search_mods(q.strip(), compat=compat.upper())
        return {"ok": True, "items": items}
    except Exception as exc:
        logger.error("모드 검색 오류: %s", exc, exc_info=True)
        return {"ok": False, "msg": f"검색 중 오류가 발생했습니다: {exc}"}


@router.get("/arcanes")
async def api_search_arcanes(q: str = Query(default="", alias="q")):
    """아케인 이름 검색.

    ``GET /api/calc/arcanes?q=몰트``
    """
    try:
        items = await search_arcanes(q.strip())
        return {"ok": True, "items": items}
    except Exception as exc:
        logger.error("아케인 검색 오류: %s", exc, exc_info=True)
        return {"ok": False, "msg": f"검색 중 오류가 발생했습니다: {exc}"}


@router.get("/shards")
async def api_get_shards():
    """아케인 샤드 정적 데이터 반환.

    ``GET /api/calc/shards``
    """
    return {"ok": True, "shards": ARCHON_SHARDS}


@router.post("/compute")
async def api_compute(req: ComputeRequest):
    """워프레임 스탯 계산.

    ``POST /api/calc/compute``

    요청 body: ``{"base": {...}, "mods": [...], "shards": [...], "arcanes": [...]}``
    """
    try:
        result = calc_warframe_stats(
            base=req.base,
            mods=[m.dict() for m in req.mods],
            shards=[s.dict() for s in req.shards],
            arcanes=[a.dict() for a in req.arcanes],
        )

        base_stats = {
            "health":     req.base.get("health", 100),
            "shield":     req.base.get("shield", 100),
            "armor":      req.base.get("armor", 0),
            "energy":     req.base.get("power", 150),
            "sprint":     req.base.get("sprintSpeed", 1.0),
            "strength":   100,
            "duration":   100,
            "range":      100,
            "efficiency": 100,
        }

        return {"ok": True, "stats": result, "base": base_stats}
    except KeyError as exc:
        logger.warning("compute 요청 누락 필드: %s", exc)
        return {"ok": False, "msg": f"필수 필드가 없습니다: {exc}"}
    except Exception as exc:
        logger.error("스탯 계산 오류: %s", exc, exc_info=True)
        return {"ok": False, "msg": f"계산 중 오류가 발생했습니다: {exc}"}


@router.get("/weapons")
async def api_search_weapons(
    q: str = Query(default="", alias="q"),
    type: str = Query(default="primary"),
):
    """무기 이름 검색. ``GET /api/calc/weapons?type=primary&q=브라톤``"""
    try:
        items = await search_weapons(q.strip(), weapon_type=type.lower())
        return {"ok": True, "items": items}
    except Exception as exc:
        logger.error("무기 검색 오류: %s", exc, exc_info=True)
        return {"ok": False, "msg": str(exc)}


@router.get("/weapon-mods")
async def api_search_weapon_mods(
    q: str = Query(default="", alias="q"),
    compat: str = Query(default="RIFLE"),
):
    """무기 모드 검색. ``GET /api/calc/weapon-mods?compat=RIFLE&q=세레이션``"""
    try:
        items = await search_weapon_mods(q.strip(), compat=compat.upper())
        return {"ok": True, "items": items}
    except Exception as exc:
        logger.error("무기 모드 검색 오류: %s", exc, exc_info=True)
        return {"ok": False, "msg": str(exc)}


@router.post("/compute-weapon")
async def api_compute_weapon(req: WeaponComputeRequest):
    """무기 스탯 계산. ``POST /api/calc/compute-weapon``"""
    try:
        result = calc_weapon_stats(
            base=req.base,
            mods=[m.dict() for m in req.mods],
        )
        return {"ok": True, "stats": result}
    except Exception as exc:
        logger.error("무기 스탯 계산 오류: %s", exc, exc_info=True)
        return {"ok": False, "msg": f"계산 중 오류가 발생했습니다: {exc}"}
