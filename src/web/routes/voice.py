"""음성채팅 방 관리 + WebRTC 시그널링 서버."""

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])

# ── 인메모리 방 저장소 ────────────────────────────────────────────────────────
# {room_id: {name, creator, created_at, empty_since, connections: {user_name: WebSocket}}}
_rooms: dict[str, dict] = {}

ROOM_TIMEOUT = 3600   # 1시간 (초)
MAX_ROOMS    = 20
MAX_MEMBERS  = 10


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class CreateRoomRequest(BaseModel):
    name: str
    creator: str


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _room_summary(rid: str, room: dict) -> dict:
    empty_since = room.get("empty_since")
    remaining = None
    if empty_since and not room["connections"]:
        remaining = max(0, int(ROOM_TIMEOUT - (time.time() - empty_since)))
    return {
        "id":         rid,
        "name":       room["name"],
        "creator":    room["creator"],
        "members":    list(room["connections"].keys()),
        "created_at": room["created_at"],
        "remaining":  remaining,  # 남은 시간(초), 멤버 있으면 None
    }


async def _broadcast(room: dict, msg: dict, exclude: str | None = None) -> None:
    for name, ws in list(room["connections"].items()):
        if name == exclude:
            continue
        try:
            await ws.send_json(msg)
        except Exception:
            pass


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("/rooms")
async def api_list_rooms():
    """활성 음성채팅 방 목록."""
    return {
        "ok":    True,
        "rooms": [_room_summary(rid, r) for rid, r in _rooms.items()],
    }


@router.post("/rooms")
async def api_create_room(body: CreateRoomRequest):
    """음성채팅 방 생성."""
    name    = body.name.strip()
    creator = body.creator.strip()
    if not name or not creator:
        return {"ok": False, "msg": "방 이름과 닉네임을 입력해주세요."}
    if len(name) > 30 or len(creator) > 20:
        return {"ok": False, "msg": "이름이 너무 깁니다."}
    if len(_rooms) >= MAX_ROOMS:
        return {"ok": False, "msg": f"방이 가득 찼습니다 (최대 {MAX_ROOMS}개)."}

    room_id = str(uuid.uuid4())[:8]
    _rooms[room_id] = {
        "name":        name,
        "creator":     creator,
        "created_at":  time.time(),
        "empty_since": time.time(),
        "connections": {},
    }
    logger.info("음성채팅방 생성: %s (%s) by %s", room_id, name, creator)
    return {"ok": True, "room_id": room_id, "name": name}


@router.websocket("/ws/{room_id}/{user_name}")
async def voice_ws(ws: WebSocket, room_id: str, user_name: str):
    """WebRTC 시그널링 WebSocket."""
    if room_id not in _rooms:
        await ws.close(code=4004)
        return

    room = _rooms[room_id]
    user_name = user_name[:20]

    if len(room["connections"]) >= MAX_MEMBERS:
        await ws.close(code=4008)
        return

    await ws.accept()
    room["connections"][user_name] = ws
    room["empty_since"] = None

    existing = [m for m in room["connections"] if m != user_name]
    logger.info("입장: %s → %s (%s)", user_name, room_id, room["name"])

    # 기존 멤버들에게 입장 알림
    await _broadcast(room, {
        "type":    "user_joined",
        "user":    user_name,
        "members": list(room["connections"].keys()),
    }, exclude=user_name)

    # 신규 입장자에게 현재 방 상태 전송
    await ws.send_json({"type": "room_state", "members": existing})

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")
            to_user  = data.get("to", "")

            # offer / answer / ice-candidate 중계
            if msg_type in ("offer", "answer", "ice"):
                target = room["connections"].get(to_user)
                if target:
                    try:
                        await target.send_json({**data, "from": user_name})
                    except Exception:
                        pass

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        room["connections"].pop(user_name, None)
        if not room["connections"]:
            room["empty_since"] = time.time()
        logger.info("퇴장: %s → %s", user_name, room_id)
        await _broadcast(room, {
            "type":    "user_left",
            "user":    user_name,
            "members": list(room["connections"].keys()),
        })


# ── 빈 방 청소 태스크 ─────────────────────────────────────────────────────────

async def cleanup_empty_rooms() -> None:
    """1시간 이상 빈 방을 주기적으로 삭제 (5분마다 체크)."""
    while True:
        await asyncio.sleep(300)
        now     = time.time()
        expired = [
            rid for rid, r in _rooms.items()
            if not r["connections"] and r.get("empty_since")
            and now - r["empty_since"] >= ROOM_TIMEOUT
        ]
        for rid in expired:
            name = _rooms.pop(rid, {}).get("name", rid)
            logger.info("음성채팅방 만료 삭제: %s (%s)", rid, name)
