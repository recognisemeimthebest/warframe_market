"""파밍 정보 — 드롭 테이블 데이터 수집 + 검색."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import httpx


def _strip_html(text: str) -> str:
    """HTML 태그 제거."""
    return re.sub(r"<[^>]+>", "", text).strip()

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

# 공식 드롭 테이블 (DE 제공)
_DROP_TABLE_URL = "https://drops.warframestat.us/data/all.slim.json"
_CACHE_PATH = DATA_DIR / "drop_table.json"

# 메모리 캐시: item_name(lower) → FarmingInfo
_farming_cache: dict[str, "FarmingInfo"] = {}

# 설명 캐시: slug → (description, wiki_link)
_desc_cache: dict[str, tuple[str, str]] = {}


@dataclass
class DropSource:
    """한 아이템의 드롭 출처."""
    source: str       # "Lith S1 Relic (Intact)" or "Jackal (Europa)"
    rate: str          # "11.11%" or "Rare"
    rarity: str        # "Common", "Uncommon", "Rare" (렐릭용)
    mission: str       # "Void Fissure" or "Assassination"


@dataclass
class FarmingInfo:
    """파밍 정보 종합."""
    name: str
    item_type: str     # "prime", "mod", "frame", "weapon", "resource", "other"
    drops: list[DropSource] = field(default_factory=list)
    wiki_url: str = ""
    vaulted: bool | None = None  # 프라임: 볼트 여부
    description: str = ""


_PART_KO: dict[str, str] = {
    "Blueprint": "설계도", "Neuroptics": "신경광학 헬멧", "Chassis": "섀시",
    "Systems": "시스템", "Barrel": "총열", "Receiver": "리시버", "Stock": "개머리판",
    "Blade": "블레이드", "Hilt": "힐트", "Handle": "핸들", "Grip": "그립",
    "Carapace": "카라페이스", "Cerebrum": "세레브럼", "Pouch": "파우치",
    "Upper Limb": "어퍼 림", "Lower Limb": "로워 림", "String": "스트링",
    "Guard": "가드", "Ornament": "장식",
}


def _fallback_description(name: str) -> str:
    """아이템 이름에서 한국어 설명 자동 생성 (API 없을 때)."""
    lower = name.lower()
    for en_part, ko_part in _PART_KO.items():
        if name.endswith(f" {en_part}"):
            base = name[: -(len(en_part) + 1)]
            if "prime" in lower:
                return f"{base} 제작 파츠 ({ko_part})"
            return f"{base} 제작 파츠 ({ko_part})"
    if lower.endswith("blueprint"):
        base = name[:-len(" Blueprint")]
        return f"{base} 설계도"
    return ""


async def fetch_item_description(name: str) -> tuple[str, str]:
    """아이템 설명 조회. (description, wiki_link) 반환.
    warframe.market v2 한국어 → 영어 폴백 → 자동 생성 순.
    """
    if not name:
        return "", ""
    slug = name.lower().replace(" ", "_")
    if slug in _desc_cache:
        return _desc_cache[slug]

    desc, wiki = "", ""
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True,
                                     headers={"Platform": "pc", "Language": "ko"}) as c:
            r = await c.get(f"https://api.warframe.market/v2/items/{slug}")
        if r.status_code == 200:
            i18n = r.json().get("data", {}).get("i18n", {})
            ko = i18n.get("ko", {})
            en = i18n.get("en", {})
            desc = ko.get("description") or en.get("description", "")
            wiki = ko.get("wikiLink") or en.get("wikiLink", "")
    except Exception:
        logger.debug("아이템 설명 조회 실패: %s", slug)

    if not desc:
        desc = _fallback_description(name)

    _desc_cache[slug] = (desc, wiki)
    return desc, wiki


async def refresh_drop_table() -> int:
    """드롭 테이블 다운로드 + 캐시."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(_DROP_TABLE_URL)
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("드롭 테이블 다운로드 실패")
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    count = _build_cache(data)
    logger.info("드롭 테이블 갱신: %d개 아이템", count)
    return count


def load_drop_table() -> int:
    """로컬 캐시에서 드롭 테이블 로드."""
    if not _CACHE_PATH.exists():
        logger.warning("드롭 테이블 캐시 없음: %s", _CACHE_PATH)
        return 0
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        return _build_cache(data)
    except Exception:
        logger.exception("드롭 테이블 로드 실패")
        return 0


def _build_cache(data: list | dict) -> int:
    """드롭 테이블 raw 데이터 → _farming_cache 빌드."""
    _farming_cache.clear()

    # drops.warframestat.us의 slim 포맷:
    # [{ "place": "...", "item": "...", "rarity": "...", "chance": N }, ...]
    if isinstance(data, list):
        for entry in data:
            item_name = entry.get("item", "").strip()
            if not item_name:
                continue

            key = item_name.lower()
            if key not in _farming_cache:
                _farming_cache[key] = FarmingInfo(
                    name=item_name,
                    item_type=_guess_type(item_name),
                )

            info = _farming_cache[key]
            chance_raw = entry.get("chance", 0)
            # chance가 문자열로 저장된 경우 정규화 (enemy 드롭 테이블 포맷)
            try:
                chance = float(chance_raw) if chance_raw is not None else 0.0
            except (ValueError, TypeError):
                chance = 0.0
            rate_str = f"{chance:.2f}%" if chance > 0 else ""
            rarity = entry.get("rarity", "")
            place = _strip_html(entry.get("place", ""))

            info.drops.append(DropSource(
                source=place,
                rate=rate_str,
                rarity=rarity,
                mission=_guess_mission(place),
            ))

    return len(_farming_cache)


def _guess_type(name: str) -> str:
    """아이템 이름으로 타입 추정."""
    lower = name.lower()
    if "prime" in lower and ("blueprint" in lower or "set" in lower
                              or "neuroptics" in lower or "chassis" in lower
                              or "systems" in lower or "barrel" in lower
                              or "receiver" in lower or "stock" in lower
                              or "blade" in lower or "hilt" in lower
                              or "handle" in lower or "grip" in lower):
        return "prime"
    if "mod" in lower or lower.startswith("(") or "augment" in lower:
        return "mod"
    if "blueprint" in lower:
        return "frame"
    return "other"


def _guess_mission(place: str) -> str:
    """출처로 미션 타입 추정."""
    lower = place.lower()
    if "relic" in lower:
        return "렐릭"
    if "bounty" in lower:
        return "현상금"
    if "spy" in lower:
        return "첩보"
    if "defense" in lower:
        return "방어"
    if "survival" in lower:
        return "생존"
    if "excavation" in lower:
        return "발굴"
    if "assassination" in lower:
        return "암살"
    if "disruption" in lower:
        return "붕괴"
    return ""


def search_farming(query: str, limit: int = 5) -> list[dict]:
    """파밍 정보 검색. 정확 매칭 + 퍼지 매칭."""
    if not _farming_cache:
        load_drop_table()

    q = query.strip().lower()
    if not q:
        return []

    # 한글 입력이면 영문으로 변환 시도
    has_korean = any('\uac00' <= c <= '\ud7a3' for c in q)
    if has_korean:
        converted = False
        try:
            from src.market.items import _ko_to_slug, _slug_to_en_name
            q_no_space = q.replace(" ", "")
            # 1. 정확 slug 매칭
            slug = _ko_to_slug.get(q) or _ko_to_slug.get(q_no_space)
            if not slug:
                # 2. 부분 매칭 — "메사"가 포함된 slug 찾기
                for ko_key, s in _ko_to_slug.items():
                    if q in ko_key or q_no_space in ko_key.replace(" ", ""):
                        slug = s
                        break
            if slug:
                # slug → 영문명: _slug_to_en_name 우선, 없으면 slug에서 직접 생성
                en = _slug_to_en_name.get(slug, "")
                if not en:
                    en = slug.replace("_", " ")
                en = en.lower()
                # "mesa prime set" → "mesa" 기본명 추출
                for suffix in (" prime set", " prime", " set", " blueprint",
                               " neuroptics", " chassis", " systems"):
                    if en.endswith(suffix):
                        en = en[: -len(suffix)]
                        break
                if en:
                    q = en
                    converted = True
        except ImportError:
            pass

        # 3. _ko_to_slug 실패 시 riven 무기명 사전으로 재시도
        if not converted:
            try:
                from src.market.auction import _RIVEN_KO_MANUAL
                q_no_space = q.replace(" ", "")
                en = (_RIVEN_KO_MANUAL.get(q)
                      or _RIVEN_KO_MANUAL.get(q_no_space))
                if not en:
                    for ko_key, val in _RIVEN_KO_MANUAL.items():
                        if q in ko_key or q_no_space in ko_key.replace(" ", ""):
                            en = val
                            break
                if en:
                    q = en.replace("_", " ")
                    converted = True
            except ImportError:
                pass

        # 한글 변환 실패 — 한글 문자열로 영문 캐시를 퍼지 매칭하면 오탐이 많으므로 빈 결과 반환
        if not converted:
            return []

    # 1. 정확 매칭
    if q in _farming_cache:
        info = _farming_cache[q]
        return [_format_farming_result(info, 1.0)]

    # 2. 부분 매칭 + 퍼지 매칭
    candidates = []
    seen = set()

    for key, info in _farming_cache.items():
        # 부분 문자열
        if q in key or key in q:
            score = SequenceMatcher(None, q, key).ratio()
            if info.name not in seen:
                candidates.append((info, max(score, 0.7)))
                seen.add(info.name)
                continue

        # 퍼지
        score = SequenceMatcher(None, q, key).ratio()
        if score >= 0.5 and info.name not in seen:
            candidates.append((info, score))
            seen.add(info.name)

    candidates.sort(key=lambda x: x[1], reverse=True)
    return [_format_farming_result(info, score) for info, score in candidates[:limit]]


_MIN_RATE_THRESHOLD = 0.5  # % 미만은 전역 모드 풀 노이즈로 간주


def _format_farming_result(info: FarmingInfo, score: float) -> dict:
    """FarmingInfo → API 응답 dict."""
    # 확률 파싱: chance가 문자열로 저장된 경우도 처리
    all_drops = info.drops

    # 전역 모드 드롭 풀 노이즈 필터링:
    # drops.warframestat.us 데이터에는 모든 적/리치에 0.01~0.02% 확률로
    # 임의 모드가 드랍 가능하도록 설정된 "전역 모드 테이블" 항목이 포함됨.
    # 의미 있는 출처(≥ 0.5%)가 존재하면 저확률 노이즈를 제거.
    # 모든 출처가 저확률인 경우(진짜 희귀 드랍)는 그대로 유지.
    max_rate = max((_parse_rate(d.rate) for d in all_drops), default=0.0)
    if max_rate >= _MIN_RATE_THRESHOLD:
        # 의미있는 출처 있음 → 노이즈 제거
        filtered = [d for d in all_drops if _parse_rate(d.rate) >= _MIN_RATE_THRESHOLD]
    else:
        # 전부 저확률 → 그대로 표시 (진짜 희귀 아이템)
        filtered = all_drops

    # 확률 높은 순 정렬, 상위 15개
    sorted_drops = sorted(
        filtered,
        key=lambda d: _parse_rate(d.rate),
        reverse=True,
    )[:15]

    return {
        "name": info.name,
        "type": info.item_type,
        "score": round(score, 3),
        "vaulted": info.vaulted,
        "description": info.description,
        "wiki_url": info.wiki_url,
        "drops": [
            {
                "source": d.source,
                "rate": d.rate,
                "rarity": d.rarity,
                "mission": d.mission,
            }
            for d in sorted_drops
        ],
    }


def _parse_rate(rate_str: str) -> float:
    """확률 문자열 → float (정렬용)."""
    try:
        return float(rate_str.rstrip("%"))
    except (ValueError, AttributeError):
        return 0.0
