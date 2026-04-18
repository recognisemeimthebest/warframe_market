"""모드 + 아케인 메타데이터 — WFCD warframe-items."""

import json
import logging
import time
from pathlib import Path

from src.config import DATA_DIR
from src.http_client import get_client

logger = logging.getLogger(__name__)

_MODS_URL = "https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Mods.json"
_ARCANES_URL = "https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Arcanes.json"

_MODS_CACHE = DATA_DIR / "mods_meta.json"
_ARCANES_CACHE = DATA_DIR / "arcanes_meta.json"

_CACHE_TTL = 86400  # 24h

# 메모리 인덱스: 소문자 이름 → 원본 dict
_mods_index: dict[str, dict] = {}
_arcanes_index: dict[str, dict] = {}
_last_loaded: float = 0.0


def _max_effect(level_stats: list) -> str:
    """풀랭크(마지막 레벨) 효과 텍스트. 여러 줄이면 ' / ' 연결."""
    if not level_stats:
        return ""
    last = level_stats[-1]
    stats = last.get("stats", [])
    return " / ".join(stats) if stats else ""


def _build_index(items: list[dict], index: dict) -> None:
    index.clear()
    for item in items:
        name = item.get("name", "").strip()
        if name:
            index[name.lower()] = item


def _load_from_disk() -> None:
    """디스크 캐시 → 메모리 인덱스."""
    global _last_loaded
    pairs = [(_MODS_CACHE, _mods_index), (_ARCANES_CACHE, _arcanes_index)]
    for path, index in pairs:
        if path.exists():
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
                _build_index(items, index)
            except Exception as e:
                logger.warning("메타 캐시 로드 실패 %s: %s", path.name, e)
    _last_loaded = time.time()


async def _download(url: str, path: Path) -> bool:
    """URL 다운로드 → 파일 저장. 성공 시 True."""
    try:
        client = get_client()
        r = await client.get(url, timeout=20.0)
        r.raise_for_status()
        path.write_bytes(r.content)
        return True
    except Exception as e:
        logger.warning("다운로드 실패 %s: %s", url, e)
        return False


async def refresh_item_meta() -> None:
    """WFCD에서 모드/아케인 메타 갱신."""
    await _download(_MODS_URL, _MODS_CACHE)
    await _download(_ARCANES_URL, _ARCANES_CACHE)
    _load_from_disk()
    logger.info("모드 메타: %d개, 아케인 메타: %d개", len(_mods_index), len(_arcanes_index))


def ensure_loaded() -> None:
    """동기 초기 로드 — 디스크 캐시 있으면 캐시 사용."""
    if _mods_index or _arcanes_index:
        return
    if _MODS_CACHE.exists() or _ARCANES_CACHE.exists():
        _load_from_disk()


def _fmt_meta(item: dict) -> dict:
    return {
        "name": item.get("name", ""),
        "item_type": item.get("type", ""),
        "rarity": item.get("rarity", ""),
        "max_effect": _max_effect(item.get("levelStats", [])),
        "tradable": item.get("tradable", False),
    }


def get_mod_meta(name: str) -> dict | None:
    ensure_loaded()
    item = _mods_index.get(name.lower().strip())
    return _fmt_meta(item) if item else None


def get_arcane_meta(name: str) -> dict | None:
    ensure_loaded()
    item = _arcanes_index.get(name.lower().strip())
    return _fmt_meta(item) if item else None


def get_item_meta(name: str) -> dict | None:
    """모드 또는 아케인 메타 반환 (모드 우선)."""
    return get_mod_meta(name) or get_arcane_meta(name)
