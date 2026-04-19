"""가상 모딩 계산기 API 라우트."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.wiki.calc import (
    ARCHON_SHARDS,
    calc_warframe_stats,
    search_arcanes,
    search_mods,
    search_warframes,
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


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("/warframes")
async def api_search_warframes(q: str = Query(default="", alias="q")):
    """워프레임 이름 검색.

    ``GET /api/calc/warframes?q=라이노``
    """
    try:
        # q 없으면 드롭다운용 전체 목록 (200개), 검색어 있으면 상위 10개
        limit = 200 if not q.strip() else 10
        items = await search_warframes(q.strip(), limit=limit)
        return {"ok": True, "items": items}
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
