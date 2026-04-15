"""워프레임/무기 스킨 검색 — Fandom Wiki API 사용."""

import asyncio
import logging
import re
import time
from difflib import SequenceMatcher

import httpx

from src.http_client import get_client

logger = logging.getLogger(__name__)

WIKI_API = "https://warframe.fandom.com/api.php"

# 타입별 검색 접미어
SKIN_TYPE_SUFFIX = {
    "warframe": "skin",
    "primary": "primary weapon skin",
    "secondary": "secondary weapon skin",
    "melee": "melee skin",
}

# 타입별 결과 필터 (제목에 반드시 포함되어야 하는 키워드)
SKIN_TYPE_FILTERS = {
    "warframe": ["skin", "collection", "deluxe", "palatine", "tennogen"],
    "primary": ["skin", "collection", "palatine"],
    "secondary": ["skin", "collection", "palatine"],
    "melee": ["skin", "collection", "palatine"],
}

# 타입별 제목 제외 키워드 — 다른 타입의 스킨이 섞이지 않도록
SKIN_TYPE_EXCLUDES = {
    "warframe": [],
    "primary":   ["secondary", "melee"],
    "secondary": ["primary", "melee"],
    "melee":     ["primary", "secondary"],
}

# 워프레임 전용 키워드 (무기 타입에서 공통 제외)
_WARFRAME_ONLY_KEYWORDS = ["deluxe", "tennogen"]

# 결과 캐시 {key: (timestamp, data)}
_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 3600  # 1시간


# 워프레임/무기 한글명 직접 매핑 (market DB에 없는 항목 포함)
_KO_SKIN_NAMES: dict[str, str] = {
    # 워프레임
    "엑스칼리버": "Excalibur", "엑칼": "Excalibur",
    "볼트": "Volt",
    "매그": "Mag",
    "애쉬": "Ash",
    "트리니티": "Trinity",
    "엠버": "Ember",
    "보반": "Vauban",
    "사르인": "Saryn",
    "라이노": "Rhino",
    "노바": "Nova",
    "로키": "Loki",
    "오베론": "Oberon",
    "하이드로이드": "Hydroid",
    "네크로스": "Nekros",
    "제피르": "Zephyr",
    "메사": "Mesa",
    "이나로스": "Inaros",
    "이바라": "Ivara",
    "티타니아": "Titania",
    "나이더스": "Nidus",
    "옥타비아": "Octavia",
    "나타": "Nezha",
    "해로우": "Harrow",
    "코라": "Khora",
    "가라": "Garuda",
    "바우반": "Vauban",
    "오공": "Wukong", "우콩": "Wukong",
    "힐드린": "Hildryn",
    "위습": "Wisp",
    "가우스": "Gauss",
    "지안": "Gian", "자얀": "Gian",
    "프로티아": "Protea",
    "자쿠": "Xaku",
    "라보스": "Lavos",
    "파인": "Phane",
    "세바고스": "Sevagoth",
    "칼리반": "Caliban",
    "구르마그": "Gourmagul",
    "스티아낙스": "Styanax",
    "단테": "Dante",
    "오필리아": "Opaline",
    # 무기 (자주 쓰는 것)
    "니카나": "Nikana",
    "스카나": "Skana",
    "버스튼": "Burston",
    "패리스": "Paris",
    "루프나": "Rufna",
}


def _has_korean(text: str) -> bool:
    return any("\uAC00" <= ch <= "\uD7A3" or "\u3131" <= ch <= "\u318E" for ch in text)


def _jamo(text: str) -> str:
    """한글 음절을 자모로 분해 (비한글은 그대로)."""
    CHOSUNG  = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
    JUNGSUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
    JONGSUNG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"
    out = []
    for ch in text:
        if "가" <= ch <= "힣":
            code = ord(ch) - 0xAC00
            jong = code % 28
            code //= 28
            out.append(CHOSUNG[code // 21])
            out.append(JUNGSUNG[code % 21])
            if jong:
                out.append(JONGSUNG[jong])
        else:
            out.append(ch)
    return "".join(out)


def _ko_to_en_query(query: str) -> str:
    """한글 쿼리를 영문 이름으로 변환. 변환 실패 시 원문 반환."""
    q = query.strip()
    q_clean = q.replace(" ", "")

    # 1. 직접 매핑 우선 확인
    direct = _KO_SKIN_NAMES.get(q) or _KO_SKIN_NAMES.get(q_clean)
    if direct:
        return direct

    # 2. _KO_SKIN_NAMES 키들과 자모 유사도 비교 (오타 허용)
    q_jamo = _jamo(q_clean)
    best_score, best_en = 0.0, ""
    for ko_key, en_val in _KO_SKIN_NAMES.items():
        score = SequenceMatcher(None, q_jamo, _jamo(ko_key)).ratio()
        if score > best_score:
            best_score, best_en = score, en_val
    if best_score >= 0.75:
        return best_en

    # 3. market DB 퍼지 검색
    try:
        from src.market.items import search_items
        results = search_items(q, limit=1)
        if results and results[0].score >= 0.65:
            en = results[0].name
            # 스킨 검색용: " Set", " Prime" 접미어 제거
            en = re.sub(r"\s+Set$", "", en, flags=re.IGNORECASE).strip()
            en = re.sub(r"\s+Prime$", "", en, flags=re.IGNORECASE).strip()
            return en
    except Exception:
        pass
    return q


async def search_skins(query: str, skin_type: str = "warframe") -> list[dict]:
    """
    쿼리와 타입으로 스킨 검색.
    한글 입력 시 자동으로 영문 이름으로 변환.
    반환: [{"name": str, "image": str, "page": str, "type": str}]
    """
    if _has_korean(query):
        query = _ko_to_en_query(query)

    cache_key = f"{query.lower()}:{skin_type}"
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            return data

    suffix = SKIN_TYPE_SUFFIX.get(skin_type, "skin")
    search_term = f"{query} {suffix}"
    filters = SKIN_TYPE_FILTERS.get(skin_type, ["skin"])
    excludes = SKIN_TYPE_EXCLUDES.get(skin_type, [])
    is_weapon_type = skin_type in ("primary", "secondary", "melee")

    try:
        c = get_client()
        # 1단계: 위키 검색
        r = await c.get(WIKI_API, params={
            "action": "query",
            "list": "search",
            "srsearch": search_term,
            "srnamespace": 0,
            "srlimit": 30,
            "format": "json",
        })
        r.raise_for_status()
        results = r.json().get("query", {}).get("search", [])

        # 스킨 관련 페이지만 필터
        def _is_valid(title: str) -> bool:
            t = title.lower()
            if not any(kw in t for kw in filters):
                return False
            # 다른 타입 키워드가 제목에 있으면 제외
            if any(kw in t for kw in excludes):
                return False
            return True

        skin_pages = [p for p in results if _is_valid(p["title"])][:12]

        if not skin_pages:
            _cache[cache_key] = (time.time(), [])
            return []

        # 2단계: 각 페이지의 썸네일 조회
        titles_str = "|".join(p["title"] for p in skin_pages)
        r2 = await c.get(WIKI_API, params={
            "action": "query",
            "titles": titles_str,
            "prop": "pageimages",
            "pithumbsize": 320,
            "format": "json",
        })
        r2.raise_for_status()
        pages_data = r2.json().get("query", {}).get("pages", {})

        skins = []
        for page in pages_data.values():
            if page.get("missing") is not None:
                continue
            title = page.get("title", "")
            thumb = page.get("thumbnail", {})
            image_url = thumb.get("source", "")
            skins.append({
                "name": title,
                "image": image_url,
                "page": f"https://warframe.fandom.com/wiki/{title.replace(' ', '_')}",
                "type": skin_type,
            })

        # 이미지 없는 항목은 맨 뒤로
        skins.sort(key=lambda x: (0 if x["image"] else 1, x["name"]))

        _cache[cache_key] = (time.time(), skins)
        logger.info("스킨 검색: query=%s type=%s → %d개", query, skin_type, len(skins))
        return skins

    except Exception:
        logger.exception("스킨 검색 실패: query=%s type=%s", query, skin_type)
        return []
