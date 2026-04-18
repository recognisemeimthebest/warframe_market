"""overframe.gg 참고 빌드 — 비공식 API 클라이언트.

overframe.gg 공개 API는 서버사이드 필터링을 지원하지 않습니다.
대신 상위 1000개 빌드를 1시간 캐시로 가져온 뒤 item slug으로 클라이언트사이드 필터링합니다.
각 빌드 URL 형식: /build/{id}/{item-slug}/{title}/
"""

import asyncio
import json as _json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from src.http_client import get_client

logger = logging.getLogger(__name__)

_BASE = "https://overframe.gg/api/v1"

# 주요 스탯 한글 레이블
# overframe.gg API 실제 키: 워프레임 → AVATAR_*, 무기 → WEAPON_*
_STAT_KO: dict[str, str] = {
    # 무기
    "WEAPON_CRIT_CHANCE":       "치명타 확률",
    "WEAPON_CRIT_DAMAGE":       "치명타 배수",
    "WEAPON_FIRE_RATE":         "발사속도",
    "WEAPON_PROC_CHANCE":       "상태이상 확률",
    "WEAPON_DAMAGE_AMOUNT":     "기본 데미지",
    "WEAPON_RELOAD_TIME":       "장전 시간",
    "WEAPON_AMMO_MAX":          "최대 탄약",
    "WEAPON_CLIP_MAX":          "탄창",
    # 워프레임 (AVATAR_ 접두사)
    "AVATAR_SHIELD_MAX":        "실드",
    "AVATAR_HEALTH_MAX":        "체력",
    "AVATAR_ARMOUR":            "방어도",
    "AVATAR_POWER_MAX":         "에너지",
    "AVATAR_SPRINT_SPEED":      "이동속도",
    "AVATAR_ABILITY_STRENGTH":  "어빌리티 위력",
    "AVATAR_ABILITY_DURATION":  "어빌리티 지속시간",
    "AVATAR_ABILITY_RANGE":     "어빌리티 범위",
    "AVATAR_ABILITY_EFFICIENCY": "어빌리티 효율",
}

_SHOW_STATS_WEAPON = [
    "WEAPON_DAMAGE_AMOUNT", "WEAPON_CRIT_CHANCE",
    "WEAPON_CRIT_DAMAGE", "WEAPON_PROC_CHANCE", "WEAPON_FIRE_RATE",
    "WEAPON_CLIP_MAX", "WEAPON_RELOAD_TIME",
]
_SHOW_STATS_FRAME = [
    "AVATAR_HEALTH_MAX", "AVATAR_SHIELD_MAX", "AVATAR_ARMOUR",
    "AVATAR_POWER_MAX", "AVATAR_ABILITY_STRENGTH", "AVATAR_ABILITY_DURATION",
    "AVATAR_ABILITY_RANGE", "AVATAR_ABILITY_EFFICIENCY",
]

# ── 전역 캐시 ──────────────────────────────────────────────────────────────
# overframe.gg API는 필터링 파라미터를 무시하므로 상위 빌드 전체를 캐시한 뒤
# 클라이언트에서 URL 패턴으로 아이템별 필터링합니다.
_builds_cache: list[dict] = []
_cache_time: datetime | None = None
_CACHE_TTL = timedelta(hours=1)
_CACHE_LIMIT = 1000  # 상위 1000개면 대부분 아이템의 인기 빌드 커버 가능
_cache_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """asyncio.Lock 지연 초기화 (이벤트 루프 시작 후 생성)."""
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


# ── 유틸리티 ───────────────────────────────────────────────────────────────

def _fmt_stat(key: str, val: float) -> str:
    """스탯 값 포매팅."""
    # 배수/속도 계열: 소수점 표시
    if key in ("WEAPON_CRIT_DAMAGE", "AVATAR_SPRINT_SPEED"):
        return f"{val:.2f}x"
    # 비율 계열: 백분율 (0~1 범위 → %)
    if "CHANCE" in key or "EFFICIENCY" in key \
            or "STRENGTH" in key or "DURATION" in key or "RANGE" in key:
        # API 값이 이미 퍼센트(예: 1.275 = 127.5%)인지, 0-1 범위인지 구분
        # AVATAR_ABILITY_* 는 곱수(1.0 기준), WEAPON_*_CHANCE 는 0~1 소수
        if "WEAPON" in key and "CHANCE" in key:
            return f"{val * 100:.1f}%"
        if "AVATAR_ABILITY" in key:
            return f"{val * 100:.0f}%"
        return f"{val:.0f}%"
    return f"{val:.0f}"


def _slug_to_overframe(slug: str) -> str:
    """warframe.market slug(underscore) → overframe.gg slug(kebab), 불필요한 접미사 제거."""
    s = slug.replace("_", "-")
    for suffix in ("-set", "-blueprint", "-neuroptics", "-chassis", "-systems",
                   "-systems-blueprint", "-neuroptics-blueprint", "-chassis-blueprint"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s


def _build_summary(raw: dict, item_type: str) -> dict:
    """overframe.gg 빌드 dict → 앱 응답 dict."""
    stats_raw = raw.get("stats") or {}
    show_keys = _SHOW_STATS_FRAME if item_type == "warframe" else _SHOW_STATS_WEAPON
    stats = []
    for k in show_keys:
        if k in stats_raw:
            stats.append({
                "label": _STAT_KO.get(k, k),
                "value": _fmt_stat(k, stats_raw[k]),
            })

    # 상대 URL → 절대 URL 변환
    url = raw.get("url", "")
    if url and not url.startswith("http"):
        url = f"https://overframe.gg{url}"

    # description 마크다운 → 첫 단락만 (모달 요약용)
    # 헤더(#)·빈줄·코드블록 제거 후 첫 의미 있는 텍스트 최대 300자
    desc_raw = raw.get("description") or ""
    desc_lines = [l.strip() for l in desc_raw.splitlines()
                  if l.strip() and not l.strip().startswith("#")
                  and not l.strip().startswith("```")]
    desc_short = " ".join(desc_lines)[:300].strip()
    if len(" ".join(desc_lines)) > 300:
        desc_short += "…"

    return {
        "id":        raw.get("id"),
        "title":     raw.get("title", ""),
        "score":     raw.get("score", 0),
        "formas":    raw.get("formas", 0),
        "pt_cost":   raw.get("platinum_cost"),
        "endo_cost": raw.get("endo_cost"),
        "url":       url,
        "author":    (raw.get("author") or {}).get("username", ""),
        "stats":     stats,
        "guide_len": raw.get("guide_wordcount", 0),
        "desc":      desc_short,   # 빌드 요약 설명 (모달용)
    }


# ── 캐시 관리 ──────────────────────────────────────────────────────────────

async def _get_cached_builds() -> list[dict]:
    """상위 빌드를 캐시에서 반환. TTL 만료 시 overframe.gg에서 갱신."""
    global _builds_cache, _cache_time

    now = datetime.now()
    if _cache_time and (now - _cache_time) < _CACHE_TTL and _builds_cache:
        return _builds_cache

    lock = _get_lock()
    async with lock:
        # 락 획득 후 재확인 (동시 요청 시 중복 갱신 방지)
        now = datetime.now()
        if _cache_time and (now - _cache_time) < _CACHE_TTL and _builds_cache:
            return _builds_cache

        client = get_client()
        r = await client.get(
            f"{_BASE}/builds/",
            params={"ordering": "-score", "limit": _CACHE_LIMIT},
            timeout=30.0,
            headers={"Accept": "application/json", "Referer": "https://overframe.gg/"},
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or (data if isinstance(data, list) else [])
        _builds_cache = results
        _cache_time = now
        logger.info("overframe.gg 빌드 캐시 갱신: %d개 (상위 %d)", len(results), _CACHE_LIMIT)
        return results


# ── 공개 API ───────────────────────────────────────────────────────────────

async def get_builds(overframe_slug: str, item_type: str, limit: int = 6) -> list[dict]:
    """overframe.gg 빌드 목록 조회.

    캐시된 상위 빌드에서 /{overframe_slug}/ URL 패턴으로 필터링.
    item_type: "warframe" | "weapon"
    """
    try:
        all_builds = await _get_cached_builds()
        # 빌드 URL: /build/{id}/{item-slug}/{title}/ → /{slug}/ 포함 여부로 필터
        slug_pat = f"/{overframe_slug}/"
        filtered = [b for b in all_builds if slug_pat in (b.get("url") or "")]
        # score 기준 내림차순 정렬
        filtered.sort(key=lambda x: x.get("score", 0), reverse=True)
        return [_build_summary(b, item_type) for b in filtered[:limit]]
    except Exception as e:
        logger.warning("overframe.gg 빌드 조회 실패 (%s): %s", overframe_slug, e)
        return []


# ── 모드 이름 캐시 ────────────────────────────────────────────────────────
# overframe.gg REST API에는 모드명 엔드포인트가 없음.
# 대신 /items/arsenal/{mod_id}/ HTML의 __NEXT_DATA__ 에서 이름 파싱.
# 한 번 조회한 이름은 영구 캐시(data/overframe_mod_names.json)에 저장.

_mod_names: dict[int, str] = {}
_mod_cache_path: Path | None = None
_mod_fetch_sem: asyncio.Semaphore | None = None


def _get_mod_sem() -> asyncio.Semaphore:
    global _mod_fetch_sem
    if _mod_fetch_sem is None:
        _mod_fetch_sem = asyncio.Semaphore(4)  # 동시 4요청
    return _mod_fetch_sem


def _init_mod_cache() -> None:
    global _mod_cache_path, _mod_names
    if _mod_cache_path is not None:
        return
    try:
        from src.config import DATA_DIR
        _mod_cache_path = Path(DATA_DIR) / "overframe_mod_names.json"
    except Exception:
        _mod_cache_path = Path("data/overframe_mod_names.json")
    if _mod_cache_path.exists():
        try:
            raw = _json.loads(_mod_cache_path.read_text(encoding="utf-8"))
            _mod_names = {int(k): v for k, v in raw.items()}
            logger.debug("overframe 모드 캐시 로드: %d개", len(_mod_names))
        except Exception:
            pass


def _save_mod_cache() -> None:
    if _mod_cache_path and _mod_names:
        try:
            _mod_cache_path.write_text(
                _json.dumps({str(k): v for k, v in _mod_names.items()},
                            ensure_ascii=False, indent=None),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("모드 캐시 저장 실패: %s", e)


async def _fetch_one_mod_name(mod_id: int) -> tuple[int, str]:
    """overframe.gg 아이템 페이지 HTML → __NEXT_DATA__ → 이름 파싱."""
    async with _get_mod_sem():
        try:
            client = get_client()
            r = await client.get(
                f"https://overframe.gg/items/arsenal/{mod_id}/",
                timeout=10.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            r.raise_for_status()
            m = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                r.text, re.S
            )
            if m:
                data = _json.loads(m.group(1))
                item = ((data.get("props") or {})
                        .get("pageProps") or {}).get("item") or {}
                name = item.get("name") or ""
                if name:
                    return mod_id, name
        except Exception as e:
            logger.debug("모드명 fetch 실패 (%d): %s", mod_id, e)
        return mod_id, ""


async def _resolve_mod_names(mod_ids: list[int]) -> dict[int, str]:
    """mod ID 목록 → {id: name} (캐시 우선, 없으면 병렬 fetch)."""
    _init_mod_cache()
    missing = [mid for mid in mod_ids if mid not in _mod_names]
    if missing:
        results = await asyncio.gather(*[_fetch_one_mod_name(mid) for mid in missing])
        changed = False
        for mod_id, name in results:
            if name:
                _mod_names[mod_id] = name
                changed = True
        if changed:
            _save_mod_cache()
        logger.debug("모드명 조회: %d개 (새로 fetch %d개)", len(mod_ids), len(missing))
    return {mid: _mod_names.get(mid, "") for mid in mod_ids}


async def get_build_detail(build_id: int) -> dict | None:
    """빌드 상세 조회 (스탯 + 모드 목록 포함)."""
    try:
        client = get_client()
        r = await client.get(
            f"{_BASE}/builds/{build_id}/",
            timeout=10.0,
            headers={"Accept": "application/json", "Referer": "https://overframe.gg/"},
        )
        r.raise_for_status()
        raw = r.json()
        stats_raw = raw.get("stats") or {}
        item_type = "warframe" if "AVATAR_HEALTH_MAX" in stats_raw else "weapon"

        result = _build_summary(raw, item_type)

        # 모드 목록 — slots 필드에서 mod ID 추출 후 이름 조회
        slots = raw.get("slots") or []
        if slots:
            mod_ids = [s["mod"] for s in slots if s.get("mod")]
            names_map = await _resolve_mod_names(mod_ids)
            result["mods"] = [
                {"name": names_map.get(s["mod"], ""), "rank": s.get("rank", 0)}
                for s in slots if s.get("mod") and names_map.get(s["mod"])
            ]
        else:
            result["mods"] = []

        return result
    except Exception as e:
        logger.warning("overframe.gg 빌드 상세 실패 (%d): %s", build_id, e)
        return None
