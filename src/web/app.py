"""FastAPI 앱 + WebSocket 시세 조회."""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.market.api import get_item_price
from src.market.auction import (
    get_lich_items,
    get_riven_items,
    resolve_riven_weapon,
    search_lich_auctions,
    search_riven_auctions,
)
from src.market.history import get_recent_surges, init_db
from src.market.items import (
    _slug_to_ko,
    _slug_to_en_name,
    refresh_items_cache,
    refresh_ko_names,
    resolve_item,
    search_items,
)
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
)
from src.modding.share import (
    IMAGES_DIR,
    create_share,
    delete_share,
    get_items_in_category,
    get_shares,
    init_modding_db,
    save_image,
)
from src.wiki.drops import fetch_item_description, load_drop_table, refresh_drop_table, search_farming
from src.world.api import (
    get_arbitration,
    get_cycles,
    get_fissures,
    get_invasions,
    get_world_state,
)

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

    # DB 초기화
    init_db()
    init_trade_db()
    init_watchlist_db()
    init_modding_db()

    # statistics 백필 (서버 최초 시작 시 히스토리 채우기)
    asyncio.create_task(backfill_statistics(get_popular_slugs()))

    # 시세 모니터 백그라운드 시작
    _monitor_task = asyncio.create_task(run_monitor(broadcast_fn=broadcast))
    logger.info("시세 모니터 백그라운드 태스크 시작")

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
    cap = min(limit, 100)

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
    cap = min(limit, 100)

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
    """파밍 정보 검색."""
    if not q.strip():
        return {"data": []}
    results = search_farming(q, limit=limit)
    # 각 아이템 설명 병렬 조회
    descs = await asyncio.gather(
        *[fetch_item_description(r["name"]) for r in results],
        return_exceptions=True,
    )
    for r, result in zip(results, descs):
        if isinstance(result, Exception):
            continue
        desc, wiki = result
        if not r.get("description"):
            r["description"] = desc
        if not r.get("wiki_url"):
            r["wiki_url"] = wiki
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
    result = add_watch(
        user_name=body.get("user_name", "").strip(),
        item_slug=body.get("item_slug", "").strip(),
        item_name=body.get("item_name", "").strip(),
        target_price=body.get("target_price", 0),
    )
    if isinstance(result, str):
        return {"ok": False, "msg": result}
    return {"ok": True, "id": result}


@app.delete("/api/watchlist/{watch_id}")
async def api_remove_watch(watch_id: int, user_name: str = Query("")):
    """워치리스트 삭제."""
    ok = remove_watch(watch_id, user_name)
    return {"ok": ok}


# ── 모딩 공유 API ──

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


@app.delete("/api/modding/shares/{share_id}")
async def api_modding_delete_share(share_id: int, author: str = Query("")):
    """모딩 공유 삭제."""
    ok = delete_share(share_id, author=author)
    return {"ok": ok}


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
        await ws.send_text(json.dumps(resp))
        return

    # 정확 매칭 실패 → 후보 검색
    candidates = search_items(query, limit=5)
    if candidates:
        suggestions = [{"slug": c.slug, "name": c.name, "ko_name": c.ko_name} for c in candidates]
        await ws.send_text(json.dumps({
            "type": "suggest",
            "query": query,
            "items": suggestions,
        }))
    else:
        await ws.send_text(json.dumps({
            "type": "chat",
            "text": f'"{query}"에 해당하는 아이템을 찾지 못했어요.\n영문 이름이나 다른 표현으로 다시 시도해보세요!',
        }))


async def broadcast(message: dict) -> None:
    """모든 연결 클라이언트에게 메시지 전송 (알림용)."""
    data = json.dumps(message)
    disconnected = set()
    for ws in connected_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.add(ws)
    connected_clients -= disconnected
