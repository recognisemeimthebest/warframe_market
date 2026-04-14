"""렐릭 기대 수익 계산기."""

import asyncio
import logging
import re
from dataclasses import dataclass, field

from src.market.api import get_item_price
from src.market.items import resolve_item
from src.wiki.drops import _farming_cache, load_drop_table

logger = logging.getLogger(__name__)

# 정제 단계별 드롭 확률 (Common×3, Uncommon×2, Rare×1)
_REFINE_CHANCES: dict[str, dict[str, float]] = {
    "Intact":      {"Common": 25.33, "Uncommon": 11.0,  "Rare": 2.0},
    "Exceptional": {"Common": 23.33, "Uncommon": 13.0,  "Rare": 4.0},
    "Flawless":    {"Common": 20.0,  "Uncommon": 17.0,  "Rare": 6.0},
    "Radiant":     {"Common": 16.67, "Uncommon": 20.0,  "Rare": 10.0},
}

_RELIC_RE = re.compile(
    r"^((?:Axi|Lith|Meso|Neo|Requiem)\s+\S+)\s+Relic\s+\((Intact|Flawless|Radiant|Exceptional)\)$"
)


@dataclass
class RelicDrop:
    item: str           # 아이템 영문명
    rarity: str         # Common / Uncommon / Rare
    chance: float       # 드롭 확률 (%)
    price: int | None   # 현재 시세 (플랫)
    slug: str = ""      # warframe.market slug


@dataclass
class RelicResult:
    name: str                       # "Axi A6"
    refinement: str                 # "Radiant"
    drops: list[RelicDrop] = field(default_factory=list)
    expected_value: float = 0.0     # 기대 수익 (플랫)


def search_relics(query: str) -> list[str]:
    """쿼리로 렐릭 이름 검색. ex) 'axi a6' → ['Axi A6']"""
    from src.wiki.drops import _farming_cache
    q = query.strip().lower()

    # 드롭 테이블에서 고유 렐릭명 수집 (캐시)
    if not _relic_names_cache:
        _build_relic_cache()

    results = []
    for name in _relic_names_cache:
        if q in name.lower():
            results.append(name)
    results.sort()
    return results[:20]


# 렐릭 이름 캐시 (drop_table 파싱 후 빌드)
_relic_names_cache: list[str] = []
_relic_drops_cache: dict[str, list[dict]] = {}  # "Axi A6|Radiant" → drops


def _build_relic_cache() -> None:
    """drop_table에서 렐릭 목록 및 드롭 내용 캐싱."""
    from src.config import DATA_DIR
    import json

    path = DATA_DIR / "drop_table.json"
    if not path.exists():
        return

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("drop_table 로드 실패")
        return

    names_set: set[str] = set()
    for entry in raw:
        place = entry.get("place", "")
        m = _RELIC_RE.match(place)
        if not m:
            continue
        relic_name = m.group(1)   # "Axi A6"
        refinement = m.group(2)   # "Radiant"
        names_set.add(relic_name)

        key = f"{relic_name}|{refinement}"
        if key not in _relic_drops_cache:
            _relic_drops_cache[key] = []
        _relic_drops_cache[key].append({
            "item": entry.get("item", ""),
            "rarity": entry.get("rarity", "Common"),
            "chance": entry.get("chance", 0.0),
        })

    _relic_names_cache.extend(sorted(names_set))
    logger.info("렐릭 캐시 빌드: %d종", len(names_set))


async def get_relic_value(relic_name: str, refinement: str = "Radiant") -> RelicResult | None:
    """렐릭 기대 수익 계산."""
    if not _relic_names_cache:
        _build_relic_cache()

    key = f"{relic_name}|{refinement}"
    raw_drops = _relic_drops_cache.get(key)

    # Intact 데이터가 없으면 다른 단계에서 rarity만 참고
    if not raw_drops:
        # 다른 정제 단계에서 rarity 정보 보완
        for ref in ("Intact", "Exceptional", "Flawless", "Radiant"):
            alt = _relic_drops_cache.get(f"{relic_name}|{ref}")
            if alt:
                raw_drops = alt
                break
    if not raw_drops:
        return None

    chances = _REFINE_CHANCES.get(refinement, _REFINE_CHANCES["Radiant"])

    # 아이템별 확률 계산 (rarity 기준)
    # 같은 rarity 아이템 수로 확률 배분
    rarity_items: dict[str, list[str]] = {}
    for d in raw_drops:
        rarity_items.setdefault(d["rarity"], []).append(d["item"])

    # 시세 병렬 조회
    unique_items = list({d["item"] for d in raw_drops})
    slugs = {}
    for item in unique_items:
        resolved = resolve_item(item)
        if resolved:
            slugs[item] = resolved[0]  # (slug, name)

    # 병렬 가격 조회
    async def fetch_price(item: str) -> tuple[str, int | None]:
        slug = slugs.get(item)
        if not slug:
            return item, None
        try:
            price_info = await get_item_price(slug)
            return item, price_info.sell_min if price_info else None
        except Exception:
            return item, None

    price_results = await asyncio.gather(*[fetch_price(i) for i in unique_items])
    prices = dict(price_results)

    # 드롭 목록 구성
    drops: list[RelicDrop] = []
    for rarity, items in rarity_items.items():
        total_chance = chances.get(rarity, 0.0)
        per_item_chance = total_chance / len(items) if items else 0.0
        for item in items:
            drops.append(RelicDrop(
                item=item,
                rarity=rarity,
                chance=round(per_item_chance, 2),
                price=prices.get(item),
                slug=slugs.get(item, ""),
            ))

    # 기대값 = sum(확률 × 가격) / 100
    ev = sum(
        (d.chance / 100) * d.price
        for d in drops
        if d.price is not None
    )

    # 희귀도 순서로 정렬 (Rare → Uncommon → Common)
    order = {"Rare": 0, "Uncommon": 1, "Common": 2}
    drops.sort(key=lambda d: (order.get(d.rarity, 9), -(d.price or 0)))

    return RelicResult(
        name=relic_name,
        refinement=refinement,
        drops=drops,
        expected_value=round(ev, 1),
    )
