"""시세 모니터링 — 백그라운드 스캔 + 급등 감지."""

import asyncio
import logging
from datetime import datetime, timezone

from src.market.api import get_item_price
import httpx

from src.market.history import (
    SurgeItem,
    backfill_from_statistics,
    cleanup_old_data,
    get_current_price,
    get_price_at,
    get_price_days_ago,
    init_db,
    save_snapshot,
    save_surge,
)
from src.market.items import _slug_to_en_name, _slug_to_ko

logger = logging.getLogger(__name__)

# 급등 감지 기준 (변동률 %)
SURGE_THRESHOLDS: dict[str, float] = {
    "1d": 20.0,   # 1일: 20% 이상
    "7d": 30.0,   # 1주: 30% 이상
    "30d": 50.0,  # 1달: 50% 이상
}

# 인기 아이템 태그 (1시간마다 스캔)
_POPULAR_TAGS = {"prime", "arcane_enhancement", "legendary", "rare"}

# 최소 가격 (너무 싼 아이템은 급등 오탐 방지)
_MIN_PRICE = 5


def get_popular_slugs() -> list[str]:
    """인기 아이템 slug 목록 (프라임 세트, 아케인 등)."""
    import json
    from src.config import DATA_DIR

    cache_path = DATA_DIR / "items.json"
    if not cache_path.exists():
        return []

    items = json.loads(cache_path.read_text(encoding="utf-8"))
    popular = []
    for item in items:
        tags = set(item.get("tags", []))
        slug = item["slug"]
        # 프라임 세트 + 부품 (세트/부품 차익 탐지에 필요), 아케인, 레전더리/레어 모드
        if "prime" in tags:
            popular.append(slug)  # 세트와 부품 모두 포함
        elif "arcane_enhancement" in tags:
            popular.append(slug)
    return popular


def get_all_slugs() -> list[str]:
    """전체 거래 가능 아이템 slug 목록."""
    return list(_slug_to_en_name.keys())


async def scan_items(slugs: list[str], broadcast_fn=None) -> int:
    """아이템 목록의 시세를 스캔하고 스냅샷 저장. 모드/아케인은 랭크별로도 저장."""
    saved = 0
    for slug in slugs:
        try:
            price = await get_item_price(slug)
            if not price:
                continue
            # 전체 스냅샷 (rank=None)
            save_snapshot(
                slug=slug,
                sell_min=price.sell_min,
                sell_count=price.sell_count,
                buy_max=price.buy_max,
                buy_count=price.buy_count,
                avg_price=price.avg_48h,
                volume=price.volume_48h,
            )
            saved += 1
            # 모드/아케인: 랭크별 스냅샷
            if price.rank_prices:
                for rp in price.rank_prices:
                    save_snapshot(
                        slug=slug,
                        rank=rp.rank,
                        sell_min=rp.sell_min,
                        sell_count=rp.sell_count,
                        buy_max=rp.buy_max,
                        buy_count=rp.buy_count,
                        avg_price=None,
                        volume=0,
                    )
        except Exception:
            logger.warning("스캔 실패: %s", slug, exc_info=True)
    return saved


def _detect_for_rank(slug: str, rank: int | None) -> list[SurgeItem]:
    """특정 slug+rank 조합의 급등 감지."""
    surges = []
    current = get_current_price(slug, rank=rank)
    if not current or current < _MIN_PRICE:
        return surges

    checks: list[tuple[str, float | None]] = [
        ("1d", get_price_at(slug, hours_ago=24, rank=rank)),
        ("7d", get_price_days_ago(slug, days_ago=7, rank=rank)),
        ("30d", get_price_days_ago(slug, days_ago=30, rank=rank)),
    ]
    for period, old_price in checks:
        if old_price and old_price >= _MIN_PRICE:
            pct = ((current - old_price) / old_price) * 100
            if pct >= SURGE_THRESHOLDS[period]:
                surges.append(SurgeItem(
                    slug=slug, period=period, rank=rank,
                    old_price=old_price, new_price=current, change_pct=pct,
                ))
    return surges


def detect_surges(slugs: list[str]) -> list[SurgeItem]:
    """급등 감지. 전체 + 랭크별(0, MAX)로 비교."""
    surges = []
    for slug in slugs:
        # 전체 가격 급등 (rank=None)
        surges.extend(_detect_for_rank(slug, rank=None))
        # 랭크별 급등 — 랭크 데이터가 있는 아이템만
        # 0랭과 MAX랭 스냅샷이 있으면 감지
        for rank in _get_stored_ranks(slug):
            surges.extend(_detect_for_rank(slug, rank=rank))
    return surges


def _get_stored_ranks(slug: str) -> list[int]:
    """DB에 저장된 해당 아이템의 랭크 목록 (0, MAX 등)."""
    from src.market.history import get_stored_ranks
    return get_stored_ranks(slug)


async def hourly_scan(broadcast_fn=None) -> None:
    """1시간마다: 인기 아이템 스캔 + 1일 급등 감지."""
    slugs = get_popular_slugs()
    if not slugs:
        logger.warning("인기 아이템 목록 비어있음")
        return

    logger.info("시간별 스캔 시작: %d개 아이템", len(slugs))
    saved = await scan_items(slugs)
    logger.info("시간별 스캔 완료: %d개 저장", saved)

    # 1일 급등 감지
    surges = detect_surges(slugs)
    day_surges = [s for s in surges if s.period == "1d"]
    for s in day_surges:
        save_surge(s)
        ko = _slug_to_ko.get(s.slug, "")
        en = _slug_to_en_name.get(s.slug, s.slug)
        name = ko or en
        rank_tag = f" [랭크{s.rank}]" if s.rank is not None else ""
        logger.info("급등 감지 [1일]: %s%s %.0fp → %.0fp (+%.1f%%)", name, rank_tag, s.old_price, s.new_price, s.change_pct)

    # 브로드캐스트
    if broadcast_fn and day_surges:
        for s in day_surges:
            ko = _slug_to_ko.get(s.slug, "")
            en = _slug_to_en_name.get(s.slug, s.slug)
            rank_tag = f" (랭크{s.rank})" if s.rank is not None else ""
            await broadcast_fn({
                "type": "alert",
                "text": f"📈 급등 감지: {ko or en}{rank_tag} — {s.old_price:.0f}p → {s.new_price:.0f}p (+{s.change_pct:.1f}%)",
            })


async def daily_scan(broadcast_fn=None) -> None:
    """1일마다: 전체 아이템 스캔 + 7일/30일 급등 감지."""
    slugs = get_all_slugs()
    if not slugs:
        return

    logger.info("일별 스캔 시작: %d개 아이템", len(slugs))
    saved = await scan_items(slugs)
    logger.info("일별 스캔 완료: %d개 저장", saved)

    # 7일, 30일 급등 감지
    surges = detect_surges(slugs)
    week_month = [s for s in surges if s.period in ("7d", "30d")]
    for s in week_month:
        save_surge(s)

    # 오래된 데이터 정리
    cleanup_old_data(keep_days=90)

    logger.info("급등 감지: 7일 %d건, 30일 %d건",
                sum(1 for s in week_month if s.period == "7d"),
                sum(1 for s in week_month if s.period == "30d"))


async def backfill_statistics(slugs: list[str]) -> None:
    """서버 시작 시 warframe.market statistics로 히스토리 백필."""
    from src.config import MARKET_API_BASE, MARKET_RATE_LIMIT
    sem = asyncio.Semaphore(MARKET_RATE_LIMIT)
    total = 0

    async def _fetch_one(slug: str) -> None:
        nonlocal total
        async with sem:
            try:
                url = f"{MARKET_API_BASE}/items/{slug}/statistics"
                async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                             headers={"Platform": "pc", "Language": "en"}) as c:
                    r = await c.get(url)
                if r.status_code != 200:
                    return
                payload = r.json().get("payload", {}).get("statistics_closed", {})
                h48 = payload.get("48hours", [])
                d90 = payload.get("90days", [])
                n = backfill_from_statistics(slug, h48, d90)
                if n:
                    total += n
            except Exception:
                pass
            finally:
                await asyncio.sleep(1 / MARKET_RATE_LIMIT)

    await asyncio.gather(*[_fetch_one(s) for s in slugs])
    if total:
        logger.info("statistics 백필 완료: %d개 스냅샷 삽입", total)

    # 백필 완료 후 즉시 surge 감지 + 저장
    try:
        logger.info("백필 후 급등 감지 실행...")
        surges = detect_surges(slugs)
        saved_count = 0
        for s in surges:
            try:
                save_surge(s)
                saved_count += 1
                ko = _slug_to_ko.get(s.slug, "")
                en = _slug_to_en_name.get(s.slug, s.slug)
                name = ko or en
                rank_tag = f" [랭크{s.rank}]" if s.rank is not None else ""
                logger.info("급등 감지 [백필후-%s]: %s%s %.0fp → %.0fp (+%.1f%%)",
                            s.period, name, rank_tag, s.old_price, s.new_price, s.change_pct)
            except Exception:
                logger.warning("급등 저장 실패: %s", s.slug, exc_info=True)
        logger.info("백필 후 급등 감지 완료: %d건", saved_count)
    except Exception:
        logger.exception("백필 후 급등 감지 오류")


async def run_monitor(broadcast_fn=None) -> None:
    """백그라운드 모니터링 루프."""
    init_db()
    logger.info("시세 모니터 시작")

    hourly_count = 0
    while True:
        try:
            # 매시간 인기 아이템 스캔 (시작 즉시 첫 스캔)
            await hourly_scan(broadcast_fn)
            hourly_count += 1

            # 24시간마다 전체 스캔
            if hourly_count % 24 == 0:
                await daily_scan(broadcast_fn)

        except Exception:
            logger.exception("모니터링 루프 오류")

        # 1시간 대기 (다음 루프 전)
        await asyncio.sleep(3600)
