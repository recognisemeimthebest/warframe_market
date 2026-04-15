import asyncio
import logging
from dataclasses import dataclass

import httpx

from src.config import MARKET_API_BASE, MARKET_RATE_LIMIT
from src.http_client import get_client
from src.market.vault import is_vaulted

logger = logging.getLogger(__name__)

# 초당 3회 제한
_semaphore = asyncio.Semaphore(MARKET_RATE_LIMIT)

_HEADERS = {
    "Accept": "application/json",
    "Platform": "pc",
    "Language": "en",
}


@dataclass
class RankPrice:
    """특정 랭크의 시세."""
    rank: int
    sell_min: int | None = None
    sell_count: int = 0
    buy_max: int | None = None
    buy_count: int = 0


@dataclass
class ItemPrice:
    """아이템 시세 요약."""
    item_name: str
    slug: str
    sell_min: int | None = None
    sell_2nd: int | None = None       # 두 번째 저렴한 온라인 판매가 (이상치 내성)
    sell_count: int = 0
    buy_max: int | None = None
    buy_count: int = 0
    avg_48h: float | None = None
    volume_48h: int = 0
    max_rank: int | None = None       # 모드/아케인 최대 랭크
    rank_prices: list[RankPrice] | None = None  # 랭크별 가격 (0, max)
    vaulted: bool | None = None       # True=단종, False=현역, None=프라임 아님


async def _get(url: str) -> dict | None:
    """rate-limited GET 요청. 공유 httpx client 사용."""
    async with _semaphore:
        try:
            client = get_client()
            r = await client.get(url, headers=_HEADERS)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            logger.error("HTTP %s: %s", e.response.status_code, url)
            return None
        except httpx.RequestError as e:
            logger.error("요청 실패: %s — %s", url, e)
            return None
        finally:
            await asyncio.sleep(1 / MARKET_RATE_LIMIT)


async def fetch_all_items() -> list[dict]:
    """전체 아이템 목록을 가져온다. (v2 API)"""
    data = await _get("https://api.warframe.market/v2/items")
    if not data:
        return []
    return data.get("data", [])


async def fetch_item_orders(slug: str) -> list[dict]:
    """아이템 주문 목록을 가져온다. (v2 API)"""
    url = f"https://api.warframe.market/v2/orders/item/{slug}"
    data = await _get(url)
    if not data:
        return []
    return data.get("data", [])


async def fetch_item_statistics(slug: str) -> dict | None:
    """아이템 통계를 가져온다. (v1 API — 아직 v1만 제공)"""
    url = f"{MARKET_API_BASE}/items/{slug}/statistics"
    data = await _get(url)
    if not data:
        return None
    return data.get("payload", {}).get("statistics_closed", {})


def _calc_rank_price(orders: list[dict], rank: int) -> RankPrice:
    """특정 랭크의 주문에서 시세 계산."""
    active_statuses = {"ingame", "online"}
    sells = sorted(
        [o for o in orders if o["type"] == "sell"
         and o.get("user", {}).get("status") in active_statuses
         and o.get("rank") == rank],
        key=lambda o: o["platinum"],
    )
    buys = sorted(
        [o for o in orders if o["type"] == "buy"
         and o.get("user", {}).get("status") in active_statuses
         and o.get("rank") == rank],
        key=lambda o: o["platinum"],
        reverse=True,
    )
    return RankPrice(
        rank=rank,
        sell_min=sells[0]["platinum"] if sells else None,
        sell_count=len(sells),
        buy_max=buys[0]["platinum"] if buys else None,
        buy_count=len(buys),
    )


async def get_item_price(slug: str, item_name: str = "") -> ItemPrice | None:
    """아이템의 현재 시세를 종합한다."""
    orders, stats = await asyncio.gather(
        fetch_item_orders(slug),
        fetch_item_statistics(slug),
    )

    if not orders:
        return None

    # 온라인/인게임 유저의 주문만 필터
    active_statuses = {"ingame", "online"}
    sell_orders = sorted(
        [
            o for o in orders
            if o["type"] == "sell"
            and o.get("user", {}).get("status") in active_statuses
        ],
        key=lambda o: o["platinum"],
    )
    buy_orders = sorted(
        [
            o for o in orders
            if o["type"] == "buy"
            and o.get("user", {}).get("status") in active_statuses
        ],
        key=lambda o: o["platinum"],
        reverse=True,
    )

    price = ItemPrice(
        item_name=item_name or slug,
        slug=slug,
        sell_min=sell_orders[0]["platinum"] if sell_orders else None,
        sell_2nd=sell_orders[1]["platinum"] if len(sell_orders) > 1 else None,
        sell_count=len(sell_orders),
        buy_max=buy_orders[0]["platinum"] if buy_orders else None,
        buy_count=len(buy_orders),
        vaulted=is_vaulted(slug),
    )

    # 48시간 평균
    if stats:
        hours_48 = stats.get("48hours", [])
        if hours_48:
            latest = hours_48[-1]
            price.avg_48h = latest.get("avg_price")
            price.volume_48h = latest.get("volume", 0)

    # 모드/아케인 랭크 감지 — 주문에 rank가 있으면 랭크별 가격 계산
    ranks_in_orders = [o.get("rank") for o in orders if o.get("rank") is not None]
    if ranks_in_orders:
        max_rank = max(ranks_in_orders)
        price.max_rank = max_rank
        rank_prices = [_calc_rank_price(orders, 0)]
        if max_rank > 0:
            rank_prices.append(_calc_rank_price(orders, max_rank))
        price.rank_prices = rank_prices

    return price
