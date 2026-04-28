"""바로 키티어 라우트."""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Query

from src.market.baro import get_db_stats, run_scrape, sync_current_visit
from src.market.baro_model import get_model_info, predict_next_visit, train_model
from src.world.api import get_void_trader

router = APIRouter(prefix="/api/baro", tags=["baro"])
logger = logging.getLogger(__name__)

_train_lock  = asyncio.Lock()
_train_state = {"running": False, "last_result": None}


@router.get("/status")
async def api_baro_status():
    """DB 현황 + 모델 메타 + 훈련 상태."""
    stats      = get_db_stats()
    model_info = get_model_info()
    return {
        **stats,
        "model":         model_info,
        "train_running": _train_state["running"],
        "last_train":    _train_state["last_result"],
    }


@router.get("/current")
async def api_baro_current():
    """현재 방문 인벤토리 (warframe.market 시세 포함, world.py 재사용)."""
    from src.web.routes.world import _enrich_baro as _enrich  # noqa: F401 (내부 함수)
    # vendors 엔드포인트와 동일 로직: get_void_trader + 시세 enrichment
    from src.market.api import get_item_price
    from src.market.items import resolve_item

    baro = await get_void_trader()

    if baro.get("active") and baro.get("inventory"):
        async def _enrich_item(item: dict) -> dict:
            resolved = resolve_item(item["item"])
            if resolved:
                slug, _ = resolved
                try:
                    price = await get_item_price(slug)
                    if price:
                        item["market_sell"] = price.sell_min
                        item["market_buy"]  = price.buy_max
                        item["slug"]        = slug
                except Exception:
                    pass
            return item

        baro["inventory"] = list(
            await asyncio.gather(*[_enrich_item(i) for i in baro["inventory"]])
        )

    return baro


@router.get("/predict")
async def api_baro_predict(top: int = Query(default=30, ge=5, le=100)):
    """다음 방문 등장 확률 예측."""
    preds = predict_next_visit(top_n=top)
    stats = get_db_stats()
    return {
        "total_visits": stats.get("total_visits", 0),
        "model":        get_model_info(),
        "predictions":  preds,
    }


@router.post("/scrape")
async def api_baro_scrape(background_tasks: BackgroundTasks):
    """위키 Lua 모듈 스크래핑 트리거."""
    background_tasks.add_task(run_scrape)
    return {"ok": True, "message": "스크래핑 시작됨 (백그라운드)"}


@router.post("/sync")
async def api_baro_sync():
    """현재 방문 인벤토리 DB 동기화."""
    return await sync_current_visit()


@router.post("/train")
async def api_baro_train(
    background_tasks: BackgroundTasks,
    trials:  int = Query(default=200, ge=10,  le=500),
    workers: int = Query(default=4,   ge=1,   le=16),
):
    """LightGBM + Optuna 학습 트리거."""
    if _train_state["running"]:
        return {"ok": False, "message": "이미 학습 중입니다"}

    async def _run():
        _train_state["running"] = True
        try:
            result = await asyncio.to_thread(train_model, trials, workers)
            _train_state["last_result"] = result
            logger.info("바로 모델 학습 완료: AUC=%.4f", result.get("best_auc", 0))
        except Exception as e:
            logger.exception("바로 모델 학습 실패")
            _train_state["last_result"] = {"ok": False, "error": str(e)}
        finally:
            _train_state["running"] = False

    background_tasks.add_task(_run)
    return {"ok": True, "message": f"학습 시작 (trials={trials}, workers={workers})"}
