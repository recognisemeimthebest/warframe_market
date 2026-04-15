"""FastAPI 앱 + WebSocket 시세 조회."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.analytics import init_analytics_db, log_event
from src.http_client import close_client
from src.market.api import get_item_price
from src.market.history import get_price_trend, init_db
from src.market.items import (
    _slug_to_ko,
    _slug_to_en_name,
    load_part_quantities,
    refresh_items_cache,
    refresh_ko_names,
    refresh_part_quantities,
    resolve_item,
    search_items,
)
from src.market.learned_aliases import init_aliases_db, save_alias
from src.market.live_cache import run_live_cache_loop
from src.market.monitor import backfill_statistics, get_popular_slugs, run_monitor
from src.market.trade import (
    approve_user,
    delete_listing,
    init_trade_db,
    list_users,
    reject_user,
)
from src.market.watchlist import init_watchlist_db, run_watchlist_monitor
from src.market.relic import _build_relic_cache
from src.modding.share import init_modding_db
from src.web.push import init_push_db, send_push_all
from src.wiki.drops import load_drop_table, refresh_drop_table

# 라우터 import
from src.web.routes.trade import router as trade_router
from src.web.routes.world import router as world_router
from src.web.routes.market import router as market_router
from src.web.routes.auction import router as auction_router
from src.web.routes.watchlist import router as watchlist_router
from src.web.routes.modding import router as modding_router
from src.web.routes.admin import router as admin_router
from src.web.routes.push import router as push_router

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# 연결된 WebSocket 클라이언트 목록 (알림 브로드캐스트용)
connected_clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 lifecycle. deprecated on_event 대체."""
    # ── startup ──
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

    # 드롭 테이블 로드
    drop_count = load_drop_table()
    if drop_count == 0:
        try:
            drop_count = await refresh_drop_table()
        except Exception:
            logger.warning("드롭 테이블 다운로드 실패", exc_info=True)
    logger.info("드롭 테이블 로드: %d개", drop_count)
    _build_relic_cache()

    # 부품 수량 캐시
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

    # 백그라운드 태스크 시작
    asyncio.create_task(backfill_statistics(get_popular_slugs()))
    monitor_task = asyncio.create_task(run_monitor(broadcast_fn=broadcast))
    logger.info("시세 모니터 백그라운드 태스크 시작")
    asyncio.create_task(run_live_cache_loop())
    logger.info("라이브 캐시 백그라운드 태스크 시작")
    watchlist_task = asyncio.create_task(run_watchlist_monitor(broadcast_fn=broadcast))
    logger.info("워치리스트 모니터 백그라운드 태스크 시작")

    yield  # 앱 실행 중

    # ── shutdown ──
    monitor_task.cancel()
    watchlist_task.cancel()
    await close_client()


app = FastAPI(title="워프봇", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 라우터 등록
app.include_router(trade_router)
app.include_router(world_router)
app.include_router(market_router)
app.include_router(auction_router)
app.include_router(watchlist_router)
app.include_router(modding_router)
app.include_router(admin_router)
app.include_router(push_router)


# ── 페이지 서빙 ──

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
async def admin_page(request: Request):
    client_ip = request.client.host
    allowed_prefixes = ("127.", "192.168.", "10.", "172.")
    allowed_ips = set()
    if not any(client_ip.startswith(p) for p in allowed_prefixes) and client_ip not in allowed_ips:
        return HTMLResponse("403 Forbidden", status_code=403)
    return FileResponse(STATIC_DIR / "admin.html")


# ── WebSocket ──

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
            "ok": True,
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
        resp["trend"] = get_price_trend(price.slug)
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


# ── 브로드캐스트 ──

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
