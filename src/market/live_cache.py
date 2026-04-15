"""라이브 시세 캐시 — 20분마다 prime/arcane 슬러그 실시간 조회.

set-arbitrage에서 snapshot 대신 사용. online/ingame 유저 주문만 반영.
"""

import asyncio
import logging
from datetime import datetime, timezone

from src.market.api import fetch_item_orders

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 20 * 60  # 20분

# slug → {"sell_min": int|None, "buy_max": int|None, "sell_count": int}
_cache: dict[str, dict] = {}
_cache_updated_at: datetime | None = None


def get_live_price(slug: str) -> dict | None:
    """캐시에서 라이브 시세 조회. 없으면 None."""
    return _cache.get(slug)


def get_cache_info() -> dict:
    """캐시 상태 정보."""
    age_min = None
    if _cache_updated_at:
        delta = datetime.now(timezone.utc) - _cache_updated_at
        age_min = round(delta.total_seconds() / 60, 1)
    return {
        "size": len(_cache),
        "age_minutes": age_min,
        "updated_at": _cache_updated_at.isoformat() if _cache_updated_at else None,
    }


def _parse_orders(orders: list[dict]) -> dict:
    """주문 목록에서 online/ingame 최저 판매가·최고 구매가 추출."""
    active = {"ingame", "online"}
    sells = sorted(
        [o for o in orders
         if o["type"] == "sell" and o.get("user", {}).get("status") in active],
        key=lambda o: o["platinum"],
    )
    buys = sorted(
        [o for o in orders
         if o["type"] == "buy" and o.get("user", {}).get("status") in active],
        key=lambda o: o["platinum"],
        reverse=True,
    )
    return {
        "sell_min": sells[0]["platinum"] if sells else None,
        "buy_max": buys[0]["platinum"] if buys else None,
        "sell_count": len(sells),
    }


async def refresh_prime_cache() -> int:
    """prime/arcane 슬러그 전체의 라이브 시세를 갱신."""
    global _cache, _cache_updated_at

    # 순환 import 방지 — 함수 안에서 import
    from src.market.monitor import get_popular_slugs

    slugs = get_popular_slugs()
    if not slugs:
        logger.warning("라이브 캐시: 슬러그 목록 비어있음")
        return 0

    logger.info("라이브 캐시 갱신 시작: %d개 슬러그", len(slugs))
    new_cache: dict[str, dict] = {}

    for slug in slugs:
        try:
            orders = await fetch_item_orders(slug)
            if orders:
                new_cache[slug] = _parse_orders(orders)
        except Exception:
            logger.warning("라이브 캐시 실패: %s", slug, exc_info=True)

    _cache.clear()
    _cache.update(new_cache)
    _cache_updated_at = datetime.now(timezone.utc)
    logger.info("라이브 캐시 갱신 완료: %d개 항목", len(new_cache))
    return len(new_cache)


async def run_live_cache_loop() -> None:
    """백그라운드 루프: 서버 시작 즉시 첫 갱신 후 20분마다 반복."""
    while True:
        try:
            await refresh_prime_cache()
        except Exception:
            logger.exception("라이브 캐시 루프 오류")
        await asyncio.sleep(REFRESH_INTERVAL)
