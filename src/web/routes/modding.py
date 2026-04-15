"""모딩 공유 API 라우트."""

from pathlib import Path

from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.responses import FileResponse

from src.market.items import search_items
from src.modding.share import (
    IMAGES_DIR,
    SUBTYPES,
    add_like,
    create_share,
    delete_share,
    update_share,
    get_items_in_category,
    get_shares,
    get_weekly_best,
    save_image,
)

router = APIRouter(prefix="/api/modding", tags=["modding"])


@router.get("/subtypes")
async def api_modding_subtypes():
    """카테고리별 서브타입 목록."""
    return {"data": SUBTYPES}


@router.get("/category-hint")
async def api_modding_category_hint(name: str = Query("")):
    """아이템 이름으로 카테고리 추측."""
    if not name.strip():
        return {"category": None}
    items = search_items(name.strip(), limit=1)
    if not items:
        return {"category": None}
    item = items[0]
    cat = item.get("category", "")
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


@router.get("/items")
async def api_modding_items(category: str = "warframe"):
    """카테고리별 아이템 목록."""
    return {"data": get_items_in_category(category)}


@router.get("/shares")
async def api_modding_shares(category: str = "warframe", item_name: str = "", limit: int = 50):
    """모딩 공유 목록."""
    shares = get_shares(category, item_name=item_name, limit=limit)
    return {"data": [
        {
            "id": s.id, "category": s.category, "item_name": s.item_name,
            "author": s.author, "memo": s.memo, "created_at": s.created_at,
            "sub_type": s.sub_type, "has_password": s.has_password,
            "images": [f"/api/modding/images/{fname}" for fname in s.images],
            "likes": s.likes,
        }
        for s in shares
    ]}


@router.post("/shares/{share_id}/like")
async def api_modding_like(share_id: int, request: Request):
    """모딩 공유 좋아요."""
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    result = add_like(share_id, ip)
    return result


@router.get("/weekly-best")
async def api_modding_weekly_best(limit: int = 5):
    """주간 베스트 모딩."""
    items = get_weekly_best(limit=limit)
    return {"data": [
        {
            **item,
            "images": [f"/api/modding/images/{fname}" for fname in item["images"]],
        }
        for item in items
    ]}


@router.post("/shares")
async def api_modding_create_share(body: dict):
    """모딩 공유 등록."""
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


@router.post("/upload")
async def api_modding_upload(file: UploadFile):
    """이미지 업로드."""
    if not file.content_type or not file.content_type.startswith("image/"):
        return {"ok": False, "msg": "이미지 파일만 업로드 가능합니다."}

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        return {"ok": False, "msg": "파일 크기는 5MB 이하여야 합니다."}

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"

    filename = save_image(data, ext)
    return {"ok": True, "filename": filename}


@router.get("/images/{filename}")
async def api_modding_image(filename: str):
    """모딩 이미지 서빙."""
    safe_name = Path(filename).name
    filepath = IMAGES_DIR / safe_name
    if not filepath.exists():
        return {"ok": False, "msg": "not found"}
    return FileResponse(filepath)


@router.put("/shares/{share_id}")
async def api_modding_update_share(share_id: int, body: dict):
    """모딩 공유 메모 수정."""
    image_filenames = body.get("image_filenames")
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


@router.delete("/shares/{share_id}")
async def api_modding_delete_share(share_id: int, author: str = Query(""), password: str = Query("")):
    """모딩 공유 삭제."""
    result = delete_share(share_id, author=author, password=password)
    if isinstance(result, str):
        return {"ok": False, "msg": result}
    return {"ok": bool(result)}
