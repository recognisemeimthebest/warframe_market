"""시세 관련 API 라우트 — 급등, 차익탐지, 렐릭, 파밍, 아이템 검색."""

import asyncio
import sqlite3

from fastapi import APIRouter, Query

from src.analytics import log_event
from src.market.api import get_item_price
from src.market.history import DB_PATH as HISTORY_DB_PATH, get_price_trend, get_recent_surges
from src.market.items import (
    _slug_to_ko,
    _slug_to_en_name,
    get_part_quantity,
    resolve_item,
    search_items,
)
from src.market.live_cache import _cache as _live_cache_all, get_live_price
from src.market.relic import get_relic_value, search_relics
from src.market.vault import is_vaulted, is_vaulted_by_name
from src.market.item_meta import get_item_meta, get_arcane_meta
from src.wiki.drops import fetch_item_description, search_farming, search_resources
from src.http_client import get_client

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/surges")
async def api_surges(period: str = "", limit: int = 30):
    """급등 아이템 목록 API."""
    surges = get_recent_surges(limit=limit * 3)

    if period:
        surges = [s for s in surges if s["period"] == period]

    for s in surges:
        s["ko_name"] = _slug_to_ko.get(s["slug"], "")
        s["en_name"] = _slug_to_en_name.get(s["slug"], s["slug"])

    return {"data": surges[:limit]}


@router.get("/arbitrage")
async def api_arbitrage(limit: int = 40):
    """현재 판매가가 기준가보다 낮은 아이템 — 저평가 매수 기회."""
    import json as _json
    from src.config import DATA_DIR as _DATA_DIR

    ranked_slugs: list[str] = []
    try:
        _cache = _DATA_DIR / "items.json"
        if _cache.exists():
            _all = _json.loads(_cache.read_text(encoding="utf-8"))
            ranked_slugs = [it["slug"] for it in _all if (it.get("maxRank") or 0) > 0]
    except Exception:
        pass

    conn = sqlite3.connect(str(HISTORY_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        if ranked_slugs:
            ph = ",".join("?" * len(ranked_slugs))
            rows_plain = conn.execute(f"""
                SELECT p.slug, NULL AS rank, p.sell_min, p.buy_max,
                       p.avg_price AS ref_price, p.volume, p.sell_count
                FROM price_snapshot p
                INNER JOIN (
                    SELECT slug, MAX(id) AS max_id
                    FROM price_snapshot
                    WHERE sell_min IS NOT NULL AND avg_price IS NOT NULL
                      AND rank IS NULL AND sell_min > 5 AND avg_price > 5
                    GROUP BY slug
                ) latest ON p.id = latest.max_id
                WHERE p.slug NOT IN ({ph})
                  AND p.volume > 2
                  AND p.sell_min < p.avg_price * 0.8
                  AND p.sell_count >= 1
                ORDER BY CAST(p.avg_price - p.sell_min AS REAL) / p.avg_price DESC
                LIMIT ?
            """, ranked_slugs + [limit]).fetchall()
        else:
            rows_plain = conn.execute("""
                SELECT p.slug, NULL AS rank, p.sell_min, p.buy_max,
                       p.avg_price AS ref_price, p.volume, p.sell_count
                FROM price_snapshot p
                INNER JOIN (
                    SELECT slug, MAX(id) AS max_id
                    FROM price_snapshot
                    WHERE sell_min IS NOT NULL AND avg_price IS NOT NULL
                      AND rank IS NULL AND sell_min > 5 AND avg_price > 5
                    GROUP BY slug
                ) latest ON p.id = latest.max_id
                WHERE p.volume > 2
                  AND p.sell_min < p.avg_price * 0.8
                  AND p.sell_count >= 1
                ORDER BY CAST(p.avg_price - p.sell_min AS REAL) / p.avg_price DESC
                LIMIT ?
            """, (limit,)).fetchall()

        rows_ranked = conn.execute("""
            SELECT cur.slug, cur.rank, cur.sell_min, cur.buy_max,
                   ref.avg_sell AS ref_price, 0 AS volume, cur.sell_count
            FROM (
                SELECT slug, rank, sell_min, buy_max, sell_count, MAX(id) AS id
                FROM price_snapshot
                WHERE sell_min IS NOT NULL AND rank IS NOT NULL AND sell_min > 5
                GROUP BY slug, rank
            ) cur
            JOIN (
                SELECT slug, rank, AVG(sell_min) AS avg_sell
                FROM price_snapshot
                WHERE sell_min IS NOT NULL AND rank IS NOT NULL
                  AND scanned_at < datetime('now', '-1 hour')
                  AND scanned_at >= datetime('now', '-72 hours')
                GROUP BY slug, rank
                HAVING COUNT(*) >= 2
            ) ref ON cur.slug = ref.slug AND cur.rank = ref.rank
            WHERE cur.sell_min < ref.avg_sell * 0.8
            ORDER BY CAST(ref.avg_sell - cur.sell_min AS REAL) / ref.avg_sell DESC
            LIMIT ?
        """, (limit,)).fetchall()

    finally:
        conn.close()

    items = []
    for r in list(rows_plain) + list(rows_ranked):
        slug = r["slug"]
        live = get_live_price(slug) if r["rank"] is None else None
        sell = (live["sell_min"] if live and live.get("sell_min") else r["sell_min"])
        if not sell:
            continue
        ref = round(r["ref_price"])
        if not ref or sell >= ref * 0.8:
            continue
        discount = ref - sell
        discount_pct = round(discount * 100 / ref, 1) if ref else 0
        name = _slug_to_ko.get(slug) or _slug_to_en_name.get(slug) or slug.replace("_", " ").title()
        entry = {
            "slug": slug,
            "name": name,
            "sell_min": sell,
            "ref_price": ref,
            "discount": discount,
            "discount_pct": discount_pct,
            "volume": r["volume"],
            "sell_count": r["sell_count"],
            "buy_max": r["buy_max"],
        }
        if r["rank"] is not None:
            entry["rank"] = r["rank"]
        items.append(entry)

    items.sort(key=lambda x: x["discount_pct"], reverse=True)
    log_event("arbitrage_view", hit=bool(items))
    return {"data": items[:limit]}


@router.get("/set-arbitrage")
async def api_set_arbitrage(min_profit: int = 10, limit: int = 40):
    """세트 vs 부품 합산 가격 비교 — 분해/조합 차익 탐지."""
    conn = sqlite3.connect(str(HISTORY_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT p.slug, p.sell_min, p.buy_max
            FROM price_snapshot p
            INNER JOIN (
                SELECT slug, MAX(id) AS max_id
                FROM price_snapshot
                WHERE rank IS NULL
                GROUP BY slug
            ) latest ON p.id = latest.max_id
            WHERE p.sell_min IS NOT NULL OR p.buy_max IS NOT NULL
        """).fetchall()
    finally:
        conn.close()

    snapshot_map: dict[str, dict] = {
        r["slug"]: {"sell_min": r["sell_min"], "buy_max": r["buy_max"]}
        for r in rows
    }

    price_map: dict[str, dict] = {}
    for slug, snap in snapshot_map.items():
        live = get_live_price(slug)
        if live and (live.get("sell_min") is not None or live.get("buy_max") is not None):
            price_map[slug] = {"sell_min": live["sell_min"], "buy_max": live["buy_max"]}
        else:
            price_map[slug] = snap

    for slug, live in _live_cache_all.items():
        if slug not in price_map and (live.get("sell_min") is not None or live.get("buy_max") is not None):
            price_map[slug] = {"sell_min": live["sell_min"], "buy_max": live["buy_max"]}

    set_slugs = [s for s in price_map if s.endswith("_set")]

    breakdown = []
    assembly = []

    for set_slug in set_slugs:
        base = set_slug[:-4]
        parts = [s for s in price_map if s.startswith(base + "_") and not s.endswith("_set")]
        if len(parts) < 2:
            continue

        sp = price_map[set_slug]
        set_sell = sp.get("sell_min")
        set_buy = sp.get("buy_max")

        parts_sell_sum = sum(
            price_map[p]["sell_min"] * get_part_quantity(p)
            for p in parts if price_map[p].get("sell_min")
        )

        set_name = _slug_to_ko.get(set_slug) or _slug_to_en_name.get(set_slug) or set_slug.replace("_", " ").title()

        def _part_info(p_slug):
            pp = price_map[p_slug]
            qty = get_part_quantity(p_slug)
            return {
                "slug": p_slug,
                "name": _slug_to_ko.get(p_slug) or _slug_to_en_name.get(p_slug) or p_slug.replace("_", " ").title(),
                "sell_min": pp.get("sell_min"),
                "quantity": qty,
            }

        if set_sell and parts_sell_sum and parts_sell_sum - set_sell >= min_profit:
            profit = parts_sell_sum - set_sell
            breakdown.append({
                "set_slug": set_slug,
                "set_name": set_name,
                "set_sell": set_sell,
                "parts_sell_sum": parts_sell_sum,
                "profit": profit,
                "profit_pct": round(profit * 100 / set_sell, 1),
                "parts": [_part_info(p) for p in parts],
                "type": "breakdown",
            })

        if set_buy and parts_sell_sum and set_buy - parts_sell_sum >= min_profit:
            profit = set_buy - parts_sell_sum
            assembly.append({
                "set_slug": set_slug,
                "set_name": set_name,
                "set_buy": set_buy,
                "parts_sell_sum": parts_sell_sum,
                "profit": profit,
                "profit_pct": round(profit * 100 / parts_sell_sum, 1),
                "parts": [_part_info(p) for p in parts],
                "type": "assembly",
            })

    breakdown.sort(key=lambda x: x["profit_pct"], reverse=True)
    assembly.sort(key=lambda x: x["profit_pct"], reverse=True)

    return {
        "breakdown": breakdown[:limit],
        "assembly": assembly[:limit],
    }


@router.get("/relics/search")
async def api_relic_search(q: str = Query("")):
    """렐릭 이름 검색."""
    return {"data": search_relics(q)}


@router.get("/relics/value")
async def api_relic_value(name: str = Query(""), ref: str = Query("Radiant")):
    """렐릭 기대 수익 계산."""
    result = await get_relic_value(name, ref)
    if not result:
        log_event("relic_calc", name, hit=False)
        return {"ok": False, "msg": "렐릭을 찾을 수 없습니다."}
    log_event("relic_calc", name, hit=True)
    return {
        "ok": True,
        "data": {
            "name": result.name,
            "refinement": result.refinement,
            "expected_value": result.expected_value,
            "drops": [
                {
                    "item": d.item,
                    "rarity": d.rarity,
                    "chance": d.chance,
                    "price": d.price,
                    "slug": d.slug,
                }
                for d in result.drops
            ],
        },
    }


@router.get("/skins/search")
async def api_skins_search(q: str = Query(""), skin_type: str = Query("warframe")):
    """워프레임/무기 스킨 이미지 검색 (Fandom Wiki)."""
    if not q.strip():
        return {"data": []}
    from src.wiki.skins import search_skins
    results = await search_skins(q.strip(), skin_type)
    log_event("skin_search", q.strip(), hit=bool(results))
    return {"data": results}


@router.get("/farming")
async def api_farming(q: str = "", limit: int = 5):
    """파밍 정보 검색."""
    if not q.strip():
        return {"data": []}

    results = search_farming(q, limit=limit)

    if len(results) < limit:
        resource_results = search_resources(q, limit=limit - len(results))
        existing_names = {r["name"].lower() for r in results}
        resource_results = [r for r in resource_results if r["name"].lower() not in existing_names]
        results = results + resource_results

    if not results:
        resolved = resolve_item(q)
        if resolved:
            slug, display_name = resolved
            vault_status = is_vaulted(slug)
        else:
            vault_status = is_vaulted_by_name(q)
            display_name = q
            slug = ""
        if vault_status is True:
            log_event("farming_search", q, hit=False)
            return {"data": [{
                "name": display_name,
                "slug": slug,
                "type": "prime",
                "vaulted": True,
                "drops": [],
                "description": "볼트에 보관된 단종 프라임입니다. 현재 렐릭 드롭 풀에 없으므로 직접 파밍 불가능합니다. warframe.market에서 구매하거나 언볼트 이벤트를 기다려야 합니다.",
            }]}

    non_resource = [r for r in results if r.get("type") != "resource"]
    descs = await asyncio.gather(
        *[fetch_item_description(r["name"]) for r in non_resource],
        return_exceptions=True,
    )
    for r, result_desc in zip(non_resource, descs):
        if isinstance(result_desc, Exception):
            continue
        desc, wiki = result_desc
        if not r.get("description"):
            r["description"] = desc
        if not r.get("wiki_url"):
            r["wiki_url"] = wiki

    # 모드 / 아케인 메타 enrichment
    for r in results:
        t = r.get("type", "")
        if t in ("mod", "arcane"):
            meta = get_item_meta(r["name"]) or get_arcane_meta(r["name"])
            if meta:
                r["meta"] = meta
        elif t == "other":
            # type 불명확한 경우도 아케인일 수 있음
            meta = get_arcane_meta(r["name"]) or get_item_meta(r["name"])
            if meta:
                r["meta"] = meta
                r["type"] = "arcane" if "arcane" in meta.get("item_type", "").lower() else "mod"

    log_event("farming_search", q, hit=bool(results))
    return {"data": results}


@router.get("/item-meta")
async def api_item_meta(name: str = ""):
    """모드 또는 아케인 메타데이터 조회."""
    if not name.strip():
        return {"ok": False, "msg": "name 필요"}
    meta = get_item_meta(name.strip()) or get_arcane_meta(name.strip())
    if not meta:
        return {"ok": False, "msg": "메타 없음"}
    return {"ok": True, "data": meta}


@router.get("/riven/auctions")
async def api_riven_auctions(weapon: str = "", limit: int = 5):
    """warframe.market 리벤 경매 검색."""
    if not weapon.strip():
        return {"ok": False, "msg": "weapon slug 필요"}
    try:
        client = get_client()
        url = "https://api.warframe.market/v1/auctions/search"
        params = {
            "type": "riven",
            "weapon_url_name": weapon.strip(),
            "sort_by": "price_asc",
        }
        r = await client.get(url, params=params, timeout=10.0,
                             headers={"Accept": "application/json", "Language": "en"})
        r.raise_for_status()
        auctions = r.json().get("payload", {}).get("auctions", [])
        # 온라인/인게임 + visible 필터
        visible = [a for a in auctions
                   if a.get("visible") and a.get("owner", {}).get("status") in ("ingame", "online")]
        result = []
        for a in visible[:limit]:
            item = a.get("item", {})
            result.append({
                "buyout_price": a.get("buyout_price"),
                "starting_price": a.get("starting_price"),
                "owner": a.get("owner", {}).get("ingame_name", ""),
                "mod_rank": item.get("mod_rank"),
                "re_rolls": item.get("re_rolls"),
                "mastery_level": item.get("mastery_level"),
                "polarity": item.get("polarity", ""),
                "attributes": item.get("attributes", []),
            })
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


@router.get("/items/search")
async def api_items_search(q: str = "", limit: int = 10):
    """아이템 이름 검색."""
    if not q.strip():
        return {"data": []}
    results = search_items(q, limit=limit)
    return {"data": [
        {"slug": r.slug, "name": r.name, "ko_name": r.ko_name, "score": round(r.score, 3)}
        for r in results
    ]}
