"""FastAPI 앱 + WebSocket 시세 조회."""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.market.api import get_item_price
from src.market.vault import is_vaulted, is_vaulted_by_name
from src.market.auction import (
    get_lich_items,
    get_riven_items,
    resolve_riven_weapon,
    search_lich_auctions,
    search_riven_auctions,
)
from src.market.history import get_recent_surges, init_db, DB_PATH as HISTORY_DB_PATH
from src.market.items import (
    _slug_to_ko,
    _slug_to_en_name,
    get_part_quantity,
    load_part_quantities,
    refresh_items_cache,
    refresh_ko_names,
    refresh_part_quantities,
    resolve_item,
    search_items,
)
from src.market.live_cache import _cache as _live_cache_all, get_live_price, get_cache_info, run_live_cache_loop
from src.market.monitor import backfill_statistics, get_popular_slugs, run_monitor
from src.market.trade import (
    approve_user,
    create_listing,
    delete_listing,
    get_listings,
    get_user_by_name,
    init_trade_db,
    list_users,
    register_user,
    reject_user,
    revoke_user,
)
from src.market.watchlist import (
    add_watch,
    get_user_watches,
    init_watchlist_db,
    remove_watch,
    run_watchlist_monitor,
    update_watch_price,
)
from src.modding.share import (
    IMAGES_DIR,
    SUBTYPES,
    create_share,
    delete_share,
    update_share,
    get_items_in_category,
    get_shares,
    init_modding_db,
    save_image,
)
from src.wiki.drops import fetch_item_description, load_drop_table, refresh_drop_table, search_farming, search_resources
from src.wiki.skins import search_skins
from src.market.relic import get_relic_value, search_relics, _build_relic_cache
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

from src.config import VAPID_PUBLIC_KEY
from src.web.push import delete_subscription, init_push_db, save_subscription, send_push_all
from src.market.learned_aliases import delete_alias, init_aliases_db, list_aliases, save_alias
from src.analytics import init_analytics_db, log_event, get_summary

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="워프봇")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 연결된 WebSocket 클라이언트 목록 (알림 브로드캐스트용)
connected_clients: set[WebSocket] = set()

# 백그라운드 태스크
_monitor_task: asyncio.Task | None = None
_watchlist_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup() -> None:
    global _monitor_task, _watchlist_task

    try:
        count = await refresh_items_cache()
        logger.info("아이템 캐시 로드: %d개", count)
    except Exception:
        logger.warning("아이템 캐시 초기화 실패 — 로컬 캐시로 폴백", exc_info=True)
    try:
        ko_count = await refresh_ko_names()
        logger.info("한글 이름 갱신: %d개", ko_count)
    except Exception:
        logger.warning("한글 이름 갱신 실패 — 로컬 캐시로 폴백", exc_info=True)

    # 드롭 테이블 로드 (로컬 캐시 → 없으면 다운로드)
    drop_count = load_drop_table()
    if drop_count == 0:
        try:
            drop_count = await refresh_drop_table()
        except Exception:
            logger.warning("드롭 테이블 다운로드 실패", exc_info=True)
    logger.info("드롭 테이블 로드: %d개", drop_count)
    _build_relic_cache()

    # 부품 수량 캐시 로드 (없으면 백그라운드 갱신)
    qty_count = load_part_quantities()
    if qty_count == 0:
        asyncio.create_task(refresh_part_quantities())
        logger.info("부품 수량 캐시 없음 — 백그라운드에서 갱신 시작")
    else:
        logger.info("부품 수량 캐시 로드: %d개", qty_count)

    # DB 초기화
    init_db()
    init_trade_db()
    init_watchlist_db()
    init_modding_db()
    init_push_db()
    init_aliases_db()
    init_analytics_db()

    # statistics 백필 (서버 최초 시작 시 히스토리 채우기)
    asyncio.create_task(backfill_statistics(get_popular_slugs()))

    # 시세 모니터 백그라운드 시작
    _monitor_task = asyncio.create_task(run_monitor(broadcast_fn=broadcast))
    logger.info("시세 모니터 백그라운드 태스크 시작")

    # 라이브 캐시 백그라운드 시작 (세트 차익 탐지용, 20분마다 갱신)
    asyncio.create_task(run_live_cache_loop())
    logger.info("라이브 캐시 백그라운드 태스크 시작")

    # 워치리스트 모니터 백그라운드 시작
    _watchlist_task = asyncio.create_task(run_watchlist_monitor(broadcast_fn=broadcast))
    logger.info("워치리스트 모니터 백그라운드 태스크 시작")


@app.on_event("shutdown")
async def shutdown() -> None:
    if _monitor_task:
        _monitor_task.cancel()
    if _watchlist_task:
        _watchlist_task.cancel()


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
async def admin_page(request: Request):
    client_ip = request.client.host
    # 허용 IP: 로컬 + 관리자 PC 공인 IP
    allowed_prefixes = ("127.", "192.168.", "10.", "172.")
    allowed_ips = set()  # 필요시 공인 IP 추가: {"1.2.3.4"}
    if not any(client_ip.startswith(p) for p in allowed_prefixes) and client_ip not in allowed_ips:
        from fastapi.responses import HTMLResponse
        return HTMLResponse("403 Forbidden", status_code=403)
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/api/surges")
async def api_surges(period: str = "", limit: int = 30):
    """급등 아이템 목록 API."""
    surges = get_recent_surges(limit=limit * 3)  # 필터링 여유분

    if period:
        surges = [s for s in surges if s["period"] == period]

    # 한글 이름 추가
    for s in surges:
        s["ko_name"] = _slug_to_ko.get(s["slug"], "")
        s["en_name"] = _slug_to_en_name.get(s["slug"], s["slug"])

    return {"data": surges[:limit]}


# ── 거래소 API ──

@app.post("/api/trade/register")
async def api_trade_register(body: dict):
    """거래소 유저 등록 요청."""
    name = body.get("name", "").strip()
    if not name or len(name) > 20:
        return {"ok": False, "msg": "이름은 1~20자로 입력해주세요."}
    result = register_user(name)
    if isinstance(result, str):
        return {"ok": False, "msg": result}
    return {"ok": True, "user": {"id": result.id, "name": result.name, "status": result.status}}


@app.get("/api/trade/user")
async def api_trade_user(name: str = ""):
    """유저 상태 조회."""
    if not name:
        return {"user": None}
    user = get_user_by_name(name)
    if not user:
        return {"user": None}
    return {"user": {"id": user.id, "name": user.name, "status": user.status}}


@app.get("/api/trade/listings")
async def api_trade_listings(trade_type: str = "", limit: int = 50):
    """매물 목록."""
    listings = get_listings(trade_type=trade_type, limit=limit)
    return {"data": [
        {
            "id": l.id, "user_name": l.user_name, "trade_type": l.trade_type,
            "item_slug": l.item_slug, "item_name": l.item_name,
            "price": l.price, "rank": l.rank, "quantity": l.quantity,
            "memo": l.memo, "created_at": l.created_at,
        }
        for l in listings
    ]}


@app.post("/api/trade/listings")
async def api_trade_create_listing(body: dict):
    """매물 등록."""
    user_name = body.get("user_name", "").strip()
    user = get_user_by_name(user_name)
    if not user or user.status != "approved":
        return {"ok": False, "msg": "승인된 유저만 매물을 등록할 수 있습니다."}

    item_slug = body.get("item_slug", "").strip()
    item_name = body.get("item_name", "").strip()
    trade_type = body.get("trade_type", "")
    price = body.get("price", 0)
    rank = body.get("rank")
    quantity = body.get("quantity", 1)
    memo = body.get("memo", "").strip()

    if trade_type not in ("buy", "sell"):
        return {"ok": False, "msg": "trade_type은 buy 또는 sell이어야 합니다."}
    if not item_slug or not item_name:
        return {"ok": False, "msg": "아이템을 선택해주세요."}
    if not isinstance(price, int) or price < 1:
        return {"ok": False, "msg": "가격은 1p 이상이어야 합니다."}
    if not isinstance(quantity, int) or quantity < 1:
        quantity = 1
    if len(memo) > 100:
        memo = memo[:100]

    listing_id = create_listing(
        user_id=user.id, trade_type=trade_type,
        item_slug=item_slug, item_name=item_name,
        price=price, rank=rank, quantity=quantity, memo=memo,
    )
    return {"ok": True, "id": listing_id}


@app.delete("/api/trade/listings/{listing_id}")
async def api_trade_delete_listing(listing_id: int, user_name: str = Query("")):
    """매물 삭제 (본인)."""
    if not user_name:
        return {"ok": False, "msg": "유저 이름이 필요합니다."}
    ok = delete_listing(listing_id, user_name=user_name)
    return {"ok": ok, "msg": "" if ok else "삭제 권한이 없거나 존재하지 않는 매물입니다."}


# ── 월드 상태 API ──

@app.get("/api/world")
async def api_world():
    """월드 상태 전체 (균열+중재+침공+사이클)."""
    return await get_world_state()


@app.get("/api/world/fissures")
async def api_fissures():
    return {"data": await get_fissures()}


@app.get("/api/world/arbitration")
async def api_arbitration():
    return {"data": await get_arbitration()}


@app.get("/api/world/invasions")
async def api_invasions():
    return {"data": await get_invasions()}


@app.get("/api/world/cycles")
async def api_cycles():
    return {"data": await get_cycles()}


@app.get("/api/incarnon")
async def api_incarnon(search: str = "", weeks: int = 9):
    """인카논 제네시스 어댑터 주간 로테이션 조회."""
    return await get_incarnon_rotation(search=search, weeks=weeks)


# ── 상인 API ──

_vendors_static: dict | None = None


def _load_vendors_static() -> dict:
    global _vendors_static
    if _vendors_static is None:
        import json
        from src.config import DATA_DIR
        path = DATA_DIR / "vendors.json"
        try:
            _vendors_static = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _vendors_static = {"nightwave": {}, "syndicates": []}
    return _vendors_static


@app.get("/api/vendors")
async def api_vendors():
    """상인 전체 데이터 (키티어 + 테신 + 나이트웨이브 + 진영)."""
    static = _load_vendors_static()
    baro, steel_path = await asyncio.gather(
        get_void_trader(),
        get_steel_path(),
    )

    # 바로 활성화 중이면 각 아이템 시세 병렬 조회
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


# ── 차익 탐지 ──

@app.get("/api/arbitrage")
async def api_arbitrage(limit: int = 40):
    """현재 판매가가 기준가보다 낮은 아이템 — 저평가 매수 기회.

    - 비랭크 아이템: 현재 sell_min vs 48h 통계 평균가 (maxRank>0 아이템 제외)
    - 랭크 아이템(모드/아케인): rank별 현재 sell_min vs 과거 72h 내 동일 rank sell_min 평균
    """
    import sqlite3
    import json as _json

    # items.json에서 maxRank>0 slug 목록 로드 — 비랭크 쿼리에서 제외
    ranked_slugs: list[str] = []
    try:
        from src.config import DATA_DIR as _DATA_DIR
        _cache = _DATA_DIR / "items.json"
        if _cache.exists():
            _all = _json.loads(_cache.read_text(encoding="utf-8"))
            ranked_slugs = [it["slug"] for it in _all if (it.get("maxRank") or 0) > 0]
    except Exception:
        pass

    conn = sqlite3.connect(str(HISTORY_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        # ── 1. 비랭크 아이템 ──
        # maxRank>0 아이템(모드/아케인) 제외 → rank=NULL avg_price가 rank-5 기반이라 비교 불가
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

        # ── 2. 랭크 아이템(모드/아케인) ──
        # rank별 최신 sell_min vs 과거 72h 내 동일 rank sell_min 평균 (순수 판매자 가격 비교)
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
        # 비랭크 아이템은 라이브 캐시 sell_min 우선 적용
        live = get_live_price(slug) if r["rank"] is None else None
        sell = (live["sell_min"] if live and live.get("sell_min") else r["sell_min"])
        if not sell:
            continue
        ref = round(r["ref_price"])
        if not ref or sell >= ref * 0.8:  # 라이브 가격 기준 재필터
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


# ── 세트/부품 차익 ──

@app.get("/api/set-arbitrage")
async def api_set_arbitrage(min_profit: int = 10, limit: int = 40):
    """세트 vs 부품 합산 가격 비교 — 분해/조합 차익 탐지."""
    import sqlite3

    # 1. 스냅샷에서 알려진 슬러그 전체 로드 (라이브 캐시 미스 시 fallback)
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

    # 2. 라이브 캐시 우선 적용 (online/ingame 실시간 데이터)
    price_map: dict[str, dict] = {}
    for slug, snap in snapshot_map.items():
        live = get_live_price(slug)
        if live and (live.get("sell_min") is not None or live.get("buy_max") is not None):
            price_map[slug] = {"sell_min": live["sell_min"], "buy_max": live["buy_max"]}
        else:
            price_map[slug] = snap

    # 라이브 캐시에만 있는 슬러그 추가 (스냅샷 미보유 신규 아이템)
    for slug, live in _live_cache_all.items():
        if slug not in price_map and (live.get("sell_min") is not None or live.get("buy_max") is not None):
            price_map[slug] = {"sell_min": live["sell_min"], "buy_max": live["buy_max"]}

    set_slugs = [s for s in price_map if s.endswith("_set")]

    breakdown = []  # 세트 구매 → 부품 판매
    assembly  = []  # 부품 구매 → 세트 판매

    for set_slug in set_slugs:
        base = set_slug[:-4]  # "rhino_prime_set" → "rhino_prime"
        parts = [s for s in price_map if s.startswith(base + "_") and not s.endswith("_set")]
        if len(parts) < 2:
            continue

        sp = price_map[set_slug]
        set_sell  = sp.get("sell_min")
        set_buy   = sp.get("buy_max")

        # 부품별 수량 반영 (예: 배럴 × 2)
        parts_sell_sum = sum(
            price_map[p]["sell_min"] * get_part_quantity(p)
            for p in parts if price_map[p].get("sell_min")
        )
        parts_buy_sum = parts_sell_sum  # 부품 구입비 = 판매자한테 사는 금액

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

        # ① 분해 차익: 세트 판매가 < 부품 합산 판매가 → 세트 사서 부품 따로 팔기
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

        # ② 조합 차익: 부품 합산 판매가 < 세트 구매 희망가 → 부품 사서 세트로 팔기
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


# ── 렐릭 API ──

@app.get("/api/relics/search")
async def api_relic_search(q: str = Query("")):
    """렐릭 이름 검색."""
    return {"data": search_relics(q)}


@app.get("/api/relics/value")
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


# ── 스킨 API ──

@app.get("/api/skins/search")
async def api_skins_search(q: str = Query(""), skin_type: str = Query("warframe")):
    """워프레임/무기 스킨 이미지 검색 (Fandom Wiki)."""
    if not q.strip():
        return {"data": []}
    results = await search_skins(q.strip(), skin_type)
    log_event("skin_search", q.strip(), hit=bool(results))
    return {"data": results}


# ── 경매 API ──

# 무기 미지정 시 기본 조회할 인기 무기들 (카테고리별)
_POPULAR_RIVEN_BY_GROUP = {
    "primary": ["rubico", "ignis", "acceltra", "soma", "stahlta", "kuva_chakkhurr", "zarr", "tiberon"],
    "secondary": ["catchmoon", "sporelacer", "tombfinger", "pyrana", "epitaph", "nukor", "staticor", "atomos"],
    "melee": ["gram", "stropha", "nikana", "kronen", "orthos", "reaper_prime", "venka", "lesion"],
    "kitgun": ["catchmoon", "sporelacer", "tombfinger", "gaze", "vermisplicer", "rattleguts"],
    "zaw": ["plague_kripath", "plague_keewar", "sepfahn", "cyath", "balla", "dokrahm"],
    "archgun": ["mausolon", "kuva_ayanga", "grattler", "fluctus", "imperator"],
    "sentinel": ["vulklok", "deth_machine_rifle", "sweeper", "stinger", "laser_rifle"],
}
# "전체"일 때: 각 카테고리에서 인기 무기 골고루
_POPULAR_RIVEN_MIX = [
    "rubico", "ignis", "acceltra",          # primary
    "catchmoon", "sporelacer", "nukor",     # secondary
    "gram", "stropha", "nikana",            # melee
    "plague_kripath",                        # zaw
]
_POPULAR_LICH_WEAPONS = [
    "kuva_zarr", "kuva_bramma", "kuva_nukor", "tenet_arca_plasmor",
    "tenet_envoy", "kuva_hek", "tenet_cycron",
]


@app.get("/api/auction/riven")
async def api_riven_auctions(
    weapon: str = "",
    group: str = "",
    buyout_policy: str = "",
    sort_by: str = "price_asc",
    limit: int = 50,
):
    """리벤 경매 검색. 무기 미지정 시 인기 무기 자동 조회."""
    bp = buyout_policy if buyout_policy else None
    cap = min(limit, 300)

    if weapon:
        # 한글/영문/slug 입력을 리벤 무기 url_name으로 변환
        resolved = await resolve_riven_weapon(weapon)
        items = await search_riven_auctions(
            weapon_url_name=resolved,
            buyout_policy=bp,
            sort_by=sort_by,
            limit=cap,
        )
    else:
        # 카테고리에 맞는 인기 무기 선택
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


@app.get("/api/auction/lich")
async def api_lich_auctions(
    weapon: str = "",
    element: str = "",
    ephemera: str = "",
    buyout_policy: str = "",
    sort_by: str = "price_asc",
    limit: int = 50,
):
    """리치/시스터 경매 검색. 무기 미지정 시 인기 무기 자동 조회."""
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


@app.get("/api/auction/riven/items")
async def api_riven_items():
    """리벤 무기 목록 (자동완성)."""
    return {"data": await get_riven_items()}


@app.get("/api/auction/lich/items")
async def api_lich_items():
    """리치/시스터 무기 목록."""
    return {"data": await get_lich_items()}


# ── 파밍 정보 API ──

@app.get("/api/farming")
async def api_farming(q: str = "", limit: int = 5):
    """파밍 정보 검색. 드롭 테이블 + 소재 DB 통합 검색."""
    if not q.strip():
        return {"data": []}

    # 드롭 테이블 검색
    results = search_farming(q, limit=limit)

    # 결과 없거나 적으면 소재 DB도 검색
    if len(results) < limit:
        resource_results = search_resources(q, limit=limit - len(results))
        # 이미 드롭 테이블에 있는 이름 제외
        existing_names = {r["name"].lower() for r in results}
        resource_results = [r for r in resource_results if r["name"].lower() not in existing_names]
        results = results + resource_results

    # 결과가 없으면 단종 프라임 여부 확인 → 안내 카드 반환
    if not results:
        # slug로 resolve 시도
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

    # 소재 타입이 아닌 것만 설명 API 조회 (소재는 description 이미 있음)
    non_resource = [r for r in results if r.get("type") != "resource"]
    descs = await asyncio.gather(
        *[fetch_item_description(r["name"]) for r in non_resource],
        return_exceptions=True,
    )
    for r, result in zip(non_resource, descs):
        if isinstance(result, Exception):
            continue
        desc, wiki = result
        if not r.get("description"):
            r["description"] = desc
        if not r.get("wiki_url"):
            r["wiki_url"] = wiki
    log_event("farming_search", q, hit=bool(results))
    return {"data": results}


# ── 워치리스트 API ──

@app.get("/api/watchlist")
async def api_watchlist(user_name: str = ""):
    """유저 워치리스트."""
    if not user_name:
        return {"data": []}
    watches = get_user_watches(user_name)
    return {"data": [
        {
            "id": w.id, "item_slug": w.item_slug, "item_name": w.item_name,
            "target_price": w.target_price, "current_price": w.current_price,
            "status": w.status, "created_at": w.created_at,
        }
        for w in watches
    ]}


@app.post("/api/watchlist")
async def api_add_watch(body: dict):
    """워치리스트 추가."""
    slug = body.get("item_slug", "").strip()
    result = add_watch(
        user_name=body.get("user_name", "").strip(),
        item_slug=slug,
        item_name=body.get("item_name", "").strip(),
        target_price=body.get("target_price", 0),
    )
    if isinstance(result, str):
        return {"ok": False, "msg": result}
    # 등록 직후 현재가 즉시 조회
    try:
        price = await get_item_price(slug)
        if price and price.sell_min is not None:
            update_watch_price(result, price.sell_min)
    except Exception:
        pass
    return {"ok": True, "id": result}


@app.delete("/api/watchlist/{watch_id}")
async def api_remove_watch(watch_id: int, user_name: str = Query("")):
    """워치리스트 삭제."""
    ok = remove_watch(watch_id, user_name)
    return {"ok": ok}


# ── 모딩 공유 API ──

@app.get("/api/modding/subtypes")
async def api_modding_subtypes():
    """카테고리별 서브타입 목록."""
    return {"data": SUBTYPES}


@app.get("/api/modding/category-hint")
async def api_modding_category_hint(name: str = Query("")):
    """아이템 이름으로 카테고리 추측. 매칭 없으면 null."""
    if not name.strip():
        return {"category": None}
    items = search_items(name.strip(), limit=1)
    if not items:
        return {"category": None}
    item = items[0]
    cat = item.get("category", "")
    # warframe.market 카테고리 → 모딩 카테고리 매핑
    cat_map = {
        "warframes": "warframe",
        "primary_weapons": "primary",
        "secondary_weapons": "secondary",
        "melee_weapons": "melee",
        "arch_guns": "archgun",
        "arch_melee": "melee",
        "sentinels": "companion",
        "companions": "companion",
    }
    mapped = cat_map.get(cat)
    return {"category": mapped, "matched_name": item.get("en_name", "")}


@app.get("/api/modding/items")
async def api_modding_items(category: str = "warframe"):
    """카테고리별 아이템 목록."""
    return {"data": get_items_in_category(category)}


@app.get("/api/modding/shares")
async def api_modding_shares(category: str = "warframe", item_name: str = "", limit: int = 50):
    """모딩 공유 목록."""
    shares = get_shares(category, item_name=item_name, limit=limit)
    return {"data": [
        {
            "id": s.id, "category": s.category, "item_name": s.item_name,
            "author": s.author, "memo": s.memo, "created_at": s.created_at,
            "sub_type": s.sub_type, "has_password": s.has_password,
            "images": [f"/api/modding/images/{fname}" for fname in s.images],
        }
        for s in shares
    ]}


@app.post("/api/modding/shares")
async def api_modding_create_share(body: dict):
    """모딩 공유 등록 (JSON body, 이미지는 별도 업로드)."""
    result = create_share(
        category=body.get("category", ""),
        item_name=body.get("item_name", ""),
        author=body.get("author", ""),
        memo=body.get("memo", ""),
        image_filenames=body.get("image_filenames", []),
        sub_type=body.get("sub_type", ""),
        password=body.get("password", ""),
    )
    if isinstance(result, str):
        return {"ok": False, "msg": result}
    return {"ok": True, "id": result}


@app.post("/api/modding/upload")
async def api_modding_upload(file: UploadFile):
    """이미지 업로드. 파일명 반환."""
    if not file.content_type or not file.content_type.startswith("image/"):
        return {"ok": False, "msg": "이미지 파일만 업로드 가능합니다."}

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:  # 5MB 제한
        return {"ok": False, "msg": "파일 크기는 5MB 이하여야 합니다."}

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"

    filename = save_image(data, ext)
    return {"ok": True, "filename": filename}


@app.get("/api/modding/images/{filename}")
async def api_modding_image(filename: str):
    """모딩 이미지 서빙."""
    # path traversal 방지
    safe_name = Path(filename).name
    filepath = IMAGES_DIR / safe_name
    if not filepath.exists():
        return {"error": "not found"}
    return FileResponse(filepath)


@app.put("/api/modding/shares/{share_id}")
async def api_modding_update_share(share_id: int, body: dict):
    """모딩 공유 메모 수정."""
    image_filenames = body.get("image_filenames")  # None이면 이미지 변경 없음
    result = update_share(
        share_id=share_id,
        author=body.get("author", ""),
        password=body.get("password", ""),
        memo=body.get("memo", ""),
        image_filenames=image_filenames,
    )
    if isinstance(result, str):
        return {"ok": False, "msg": result}
    return {"ok": bool(result)}


@app.delete("/api/modding/shares/{share_id}")
async def api_modding_delete_share(share_id: int, author: str = Query(""), password: str = Query("")):
    """모딩 공유 삭제."""
    result = delete_share(share_id, author=author, password=password)
    if isinstance(result, str):
        return {"ok": False, "msg": result}
    return {"ok": bool(result)}


# ── 관리자 API ──

@app.get("/api/admin/users")
async def api_admin_users():
    users = list_users()
    return {"data": [{"id": u.id, "name": u.name, "status": u.status, "created_at": u.created_at} for u in users]}


@app.post("/api/admin/users/{name}/approve")
async def api_admin_approve(name: str):
    ok = approve_user(name)
    return {"ok": ok}


@app.post("/api/admin/users/{name}/revoke")
async def api_admin_revoke(name: str):
    ok = revoke_user(name)
    return {"ok": ok}


@app.delete("/api/admin/trade/{listing_id}")
async def api_admin_delete_listing(listing_id: int):
    ok = delete_listing(listing_id, is_admin=True)
    return {"ok": ok}


@app.get("/api/admin/modding")
async def api_admin_modding():
    shares = get_shares(category="", limit=200)
    return {"data": [
        {
            "id": s.id, "category": s.category, "item_name": s.item_name,
            "author": s.author, "memo": s.memo, "created_at": s.created_at,
            "images": [f"/api/modding/images/{fname}" for fname in s.images],
        }
        for s in shares
    ]}


@app.delete("/api/admin/modding/{share_id}")
async def api_admin_delete_share(share_id: int):
    ok = delete_share(share_id, is_admin=True)
    return {"ok": ok}


@app.get("/api/admin/aliases")
async def api_admin_aliases():
    """학습된 별명 목록 (관리용)."""
    return {"data": list_aliases()}


@app.delete("/api/admin/aliases")
async def api_admin_delete_alias(query: str = Query("")):
    """잘못 학습된 별명 삭제."""
    if not query:
        return {"ok": False}
    ok = delete_alias(query)
    return {"ok": ok}


@app.get("/api/admin/analytics")
async def api_admin_analytics(days: int = 7):
    """기능별 사용 통계 요약."""
    return get_summary(days)


# ── Web Push API ──

@app.get("/api/push/vapid-public-key")
async def api_vapid_key():
    return {"key": VAPID_PUBLIC_KEY}


@app.post("/api/push/subscribe")
async def api_push_subscribe(body: dict):
    try:
        save_subscription(
            endpoint=body["endpoint"],
            p256dh=body["keys"]["p256dh"],
            auth=body["keys"]["auth"],
        )
        return {"ok": True}
    except Exception:
        return {"ok": False}


@app.post("/api/push/unsubscribe")
async def api_push_unsubscribe(body: dict):
    delete_subscription(body.get("endpoint", ""))
    return {"ok": True}


# ── 아이템 검색 API (자동완성용) ──

@app.get("/api/items/search")
async def api_items_search(q: str = "", limit: int = 10):
    """아이템 이름 검색."""
    if not q.strip():
        return {"data": []}
    results = search_items(q, limit=limit)
    return {"data": [
        {"slug": r.slug, "name": r.name, "ko_name": r.ko_name, "score": round(r.score, 3)}
        for r in results
    ]}


@app.websocket("/ws")
async def websocket_chat(ws: WebSocket) -> None:
    """WebSocket 시세 조회 엔드포인트."""
    await ws.accept()
    connected_clients.add(ws)
    logger.info("클라이언트 연결 (총 %d명)", len(connected_clients))

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            user_text = msg.get("text", "").strip()

            # suggest 선택 확인 → 학습 저장 후 시세 조회
            if msg.get("type") == "confirm":
                original_query = msg.get("query", "").strip()
                slug = msg.get("slug", "").strip()
                if original_query and slug:
                    save_alias(original_query, slug)
                # slug로 바로 시세 조회
                if slug:
                    await _handle_price_query(ws, slug)
                continue

            if not user_text:
                continue

            # 관리자 명령어 처리
            if await _handle_admin_command(ws, user_text):
                continue

            # 시세 조회
            query = user_text
            for prefix in ("!시세 ", "!ㅅㅅ ", "!price "):
                if query.startswith(prefix):
                    query = query[len(prefix):]
                    break

            await _handle_price_query(ws, query)

    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(ws)
        logger.info("클라이언트 연결 해제 (총 %d명)", len(connected_clients))


async def _handle_admin_command(ws: WebSocket, text: str) -> bool:
    """관리자 명령어 처리. 처리했으면 True 반환."""
    if text.startswith("!승인 "):
        name = text.split(" ", 1)[1].strip()
        if approve_user(name):
            await ws.send_text(json.dumps({"type": "chat", "text": f'"{name}" 승인 완료!'}))
        else:
            await ws.send_text(json.dumps({"type": "chat", "text": f'"{name}" — 대기 중인 유저가 없습니다.'}))
        return True

    if text.startswith("!거절 "):
        name = text.split(" ", 1)[1].strip()
        if reject_user(name):
            await ws.send_text(json.dumps({"type": "chat", "text": f'"{name}" 거절 완료.'}))
        else:
            await ws.send_text(json.dumps({"type": "chat", "text": f'"{name}" — 대기 중인 유저가 없습니다.'}))
        return True

    if text == "!유저목록":
        users = list_users()
        if not users:
            await ws.send_text(json.dumps({"type": "chat", "text": "등록된 유저가 없습니다."}))
        else:
            status_map = {"pending": "대기", "approved": "승인", "rejected": "거절"}
            lines = [f"• {u.name} [{status_map.get(u.status, u.status)}]" for u in users]
            await ws.send_text(json.dumps({"type": "chat", "text": "유저 목록:\n" + "\n".join(lines)}))
        return True

    if text.startswith("!매물삭제 "):
        try:
            listing_id = int(text.split(" ", 1)[1].strip())
            ok = delete_listing(listing_id, is_admin=True)
            msg = f"매물 #{listing_id} 삭제 완료." if ok else f"매물 #{listing_id}를 찾을 수 없습니다."
            await ws.send_text(json.dumps({"type": "chat", "text": msg}))
        except ValueError:
            await ws.send_text(json.dumps({"type": "chat", "text": "사용법: !매물삭제 번호"}))
        return True

    return False


async def _handle_price_query(ws: WebSocket, query: str) -> None:
    """시세 조회 처리. 정확히 못 찾으면 후보를 제안한다."""
    result = resolve_item(query)

    if result:
        # 정확 매칭 → 바로 시세 조회
        slug, display_name = result
        price = await get_item_price(slug, display_name)
        if not price:
            await ws.send_text(json.dumps({
                "type": "chat",
                "text": "시세 정보를 가져오지 못했어요. 잠시 후 다시 시도해주세요.",
            }))
            return
        resp = {
            "type": "price",
            "error": False,
            "item_name": price.item_name,
            "slug": price.slug,
            "sell_min": price.sell_min,
            "sell_count": price.sell_count,
            "buy_max": price.buy_max,
            "buy_count": price.buy_count,
            "avg_48h": price.avg_48h,
            "volume_48h": price.volume_48h,
            "vaulted": price.vaulted,
        }
        if price.max_rank is not None and price.rank_prices:
            resp["max_rank"] = price.max_rank
            resp["rank_prices"] = [
                {
                    "rank": rp.rank,
                    "sell_min": rp.sell_min,
                    "sell_count": rp.sell_count,
                    "buy_max": rp.buy_max,
                    "buy_count": rp.buy_count,
                }
                for rp in price.rank_prices
            ]
        log_event("price_query", display_name, hit=True)
        await ws.send_text(json.dumps(resp))
        return

    # 정확 매칭 실패 → 후보 검색
    candidates = search_items(query, limit=5)
    if candidates:
        suggestions = [{"slug": c.slug, "name": c.name, "ko_name": c.ko_name} for c in candidates]
        log_event("price_query", query, hit=False)
        await ws.send_text(json.dumps({
            "type": "suggest",
            "query": query,
            "items": suggestions,
        }))
    else:
        log_event("price_query", query, hit=False)
        await ws.send_text(json.dumps({
            "type": "chat",
            "text": f'"{query}"에 해당하는 아이템을 찾지 못했어요.\n영문 이름이나 다른 표현으로 다시 시도해보세요!',
        }))


async def broadcast(message: dict) -> None:
    """모든 연결 클라이언트에게 메시지 전송 + 푸시 알림."""
    data = json.dumps(message)
    disconnected = set()
    for ws in connected_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.add(ws)
    connected_clients -= disconnected

    # 급등/워치리스트 알림은 푸시로도 전송
    if message.get("type") == "surge":
        name = message.get("ko_name") or message.get("en_name") or message.get("slug", "")
        pct = message.get("change_pct", 0)
        asyncio.create_task(send_push_all(
            title="급등 알림 📈",
            body=f"{name} +{pct:.0f}%",
            url="/",
        ))
    elif message.get("type") == "watchlist_alert":
        name = message.get("item_name", "")
        price = message.get("current_price", 0)
        asyncio.create_task(send_push_all(
            title="시세 감시 알림",
            body=f"{name} 목표가 도달: {price}p",
            url="/",
        ))
