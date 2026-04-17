"""거래소 게시판 API 라우트."""

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.market.board import (
    add_contact,
    create_post,
    delete_post,
    get_post,
    list_contacts,
    list_my_posts,
    list_posts,
    mark_contacts_read,
    update_post,
)
from src.market.riven_data import polarity_options, stat_options
from src.web.push import send_push_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/board", tags=["board"])


# ── Pydantic 모델 ──

class RivenStat(BaseModel):
    name: str = Field(..., max_length=64)
    value: float = Field(..., ge=-200.0, le=400.0)


class RivenPayload(BaseModel):
    weapon_name: str = Field(..., min_length=1, max_length=40)
    polarity: str = Field("", max_length=20)
    mastery_rank: int = Field(8, ge=8, le=16)
    rolls: int = Field(0, ge=0, le=999)
    stats: list[RivenStat] = []
    negative_stat: str = Field("", max_length=64)


class CreatePostBody(BaseModel):
    type: Literal["WTB", "WTS", "RIVEN"]
    item_name: str = Field(..., min_length=1, max_length=80)
    price: int = Field(..., ge=0, le=10_000_000)
    quantity: int = Field(1, ge=1, le=999)
    ign: str = Field(..., min_length=1, max_length=20)
    password: str = Field(..., min_length=2, max_length=64)
    note: str = Field("", max_length=200)
    riven: Optional[RivenPayload] = None


class UpdatePostBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=64)
    item_name: Optional[str] = Field(None, max_length=80)
    price: Optional[int] = Field(None, ge=0, le=10_000_000)
    quantity: Optional[int] = Field(None, ge=1, le=999)
    note: Optional[str] = Field(None, max_length=200)
    riven: Optional[RivenPayload] = None


class DeleteBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=64)


class ContactBody(BaseModel):
    from_ign: str = Field(..., min_length=1, max_length=20)
    message: str = Field("", max_length=200)


class MyPostsBody(BaseModel):
    ign: str = Field(..., min_length=1, max_length=20)
    password: str = Field(..., min_length=1, max_length=64)


class ContactListBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=64)


# ── 직렬화 ──

def _post_to_dict(post) -> dict:
    return {
        "id": post.id,
        "type": post.type,
        "item_name": post.item_name,
        "price": post.price,
        "quantity": post.quantity,
        "ign": post.ign,
        "note": post.note,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
        "riven": post.riven,
        "contact_count": post.contact_count,
        "unread_count": post.unread_count,
    }


# ── 라우트 ──

@router.get("/posts")
async def api_list_posts(type: str = "", limit: int = 100):
    """게시글 목록. ?type=WTB|WTS|RIVEN 으로 필터."""
    posts = list_posts(type=type or None, limit=min(max(limit, 1), 200))
    return {"ok": True, "data": [_post_to_dict(p) for p in posts]}


@router.get("/posts/{post_id}")
async def api_get_post(post_id: int):
    post = get_post(post_id)
    if not post:
        return {"ok": False, "msg": "게시글이 존재하지 않습니다."}
    return {"ok": True, "data": _post_to_dict(post)}


@router.post("/posts")
async def api_create_post(body: CreatePostBody):
    if body.type == "RIVEN" and body.riven is None:
        return {"ok": False, "msg": "리벤 정보를 입력해주세요."}

    riven_dict = None
    if body.riven:
        riven_dict = body.riven.model_dump()
        riven_dict["stats"] = [s for s in riven_dict.get("stats", []) if s.get("name")]

    try:
        post_id = create_post(
            type=body.type,
            item_name=body.item_name,
            price=body.price,
            quantity=body.quantity,
            ign=body.ign,
            password=body.password,
            note=body.note,
            riven=riven_dict,
        )
    except ValueError as e:
        return {"ok": False, "msg": str(e)}

    return {"ok": True, "id": post_id}


@router.patch("/posts/{post_id}")
async def api_update_post(post_id: int, body: UpdatePostBody):
    riven_dict = body.riven.model_dump() if body.riven else None
    if riven_dict:
        riven_dict["stats"] = [s for s in riven_dict.get("stats", []) if s.get("name")]
    ok, msg = update_post(
        post_id, body.password,
        item_name=body.item_name, price=body.price, quantity=body.quantity,
        note=body.note, riven=riven_dict,
    )
    return {"ok": ok, "msg": msg}


@router.post("/posts/{post_id}/delete")
async def api_delete_post(post_id: int, body: DeleteBody):
    ok, msg = delete_post(post_id, body.password)
    return {"ok": ok, "msg": msg}


@router.post("/posts/{post_id}/contact")
async def api_contact(post_id: int, body: ContactBody):
    """게시글에 구매/판매 문의 등록 + 푸시 알림 트리거."""
    ok, msg, post = add_contact(post_id, body.from_ign, body.message)
    if ok and post:
        type_ko = {"WTB": "삽니다", "WTS": "팝니다", "RIVEN": "리벤"}.get(post.type, post.type)
        title = f"[{type_ko}] {post.item_name}"
        body_text = f"{body.from_ign}님이 연락 — {body.message[:60] if body.message else '구매원해요'}"
        asyncio.create_task(send_push_all(title=title, body=body_text, url="/?tab=board"))
    return {"ok": ok, "msg": msg}


@router.post("/my-posts")
async def api_my_posts(body: MyPostsBody):
    """IGN+비번으로 내 게시글 목록 조회."""
    ok, msg, posts = list_my_posts(body.ign, body.password)
    if not ok:
        return {"ok": False, "msg": msg}
    return {"ok": True, "data": [_post_to_dict(p) for p in posts]}


@router.post("/posts/{post_id}/contacts")
async def api_list_contacts(post_id: int, body: ContactListBody):
    ok, msg, contacts = list_contacts(post_id, body.password)
    if not ok:
        return {"ok": False, "msg": msg}
    return {
        "ok": True,
        "data": [
            {
                "id": c.id, "from_ign": c.from_ign, "message": c.message,
                "created_at": c.created_at, "is_read": c.is_read,
            }
            for c in contacts
        ],
    }


@router.post("/posts/{post_id}/contacts/read")
async def api_mark_read(post_id: int, body: ContactListBody):
    ok, msg = mark_contacts_read(post_id, body.password)
    return {"ok": ok, "msg": msg}


@router.get("/riven/options")
async def api_riven_options():
    """리벤 작성 폼용 드롭다운 데이터."""
    return {
        "ok": True,
        "polarities": polarity_options(),
        "stats": stat_options(),
    }
