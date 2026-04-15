"""warframe.market 경매 API 프록시 — 리벤 모드 + 리치/시스터 무기."""

import asyncio
import logging
from difflib import SequenceMatcher

import httpx

from src.config import MARKET_API_BASE, MARKET_RATE_LIMIT
from src.http_client import get_client

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(MARKET_RATE_LIMIT)

_HEADERS = {
    "Accept": "application/json",
    "Platform": "pc",
    "Language": "en",
}

# 리벤 무기 한글→영문 매핑 (수동 + 자동)
_riven_ko_to_en: dict[str, str] = {}
_riven_ko_loaded = False

# 자주 사용되는 리벤 무기 한글 매핑 (마켓에 없는 일반 무기)
_RIVEN_KO_MANUAL: dict[str, str] = {
    "소벡": "sobek", "이그니스": "ignis", "글렉시온": "glaxion",
    "루비코": "rubico", "소마": "soma", "제니스": "zenith",
    "볼터": "boltor", "브라톤": "braton", "톤코어": "tonkor",
    "티버론": "tiberon", "시냅스": "synapse", "티그리스": "tigris",
    "벡티스": "vectis", "토리드": "torid", "자르": "zarr",
    "엑셀트라": "acceltra", "트럼나": "trumna", "스탈타": "stahlta",
    "엔보이": "envoy", "펄민": "fulmin", "코르바스": "corvas",
    "그람": "gram", "니카나": "nikana", "오르도스": "orthos",
    "스트로파": "stropha", "크로넨": "kronen", "레시온": "lesion",
    "갈라틴": "galatine", "리퍼": "reaper_prime", "파라세시스": "paracesis",
    "브로큰 워": "broken_war", "스키아자티": "skiajati",
    "캐치문": "catchmoon", "스포어레이서": "sporelacer", "툼핑거": "tombfinger",
    "게이즈": "gaze", "래틀것": "rattleguts", "버미스플라이서": "vermisplicer",
    "플레이그 크리파스": "plague_kripath", "플레이그 키워": "plague_keewar",
    "셉판": "sepfahn", "시아스": "cyath", "발라": "balla", "도크람": "dokrahm",
    "뉴코어": "nukor", "에피타프": "epitaph", "파이라나": "pyrana",
    "아크리드": "acrid", "아토모스": "atomos", "스태티코어": "staticor",
    "유포나": "euphona_prime", "레이저 라이플": "laser_rifle",
    "스위퍼": "sweeper", "불클락": "vulklok", "스팅어": "stinger",
    "머솔론": "mausolon", "그라틀러": "grattler", "플럭터스": "fluctus",
    "임페라토르": "imperator", "아얀가": "kuva_ayanga",
    "히스트릭스": "hystrix", "판테라": "panthera", "오그리스": "ogris",
    "자르": "zarr", "카락": "karak", "헥": "hek", "마라": "mara",
    "드락군": "drakgoon", "콤": "kohm", "페록스": "ferrox",
    "렉스": "lex", "브롱코": "bronco", "디스페어": "despair",
    "이코르": "ichor", "에텔라": "etheria", "덱스 픽시아": "dex_pixia",
    "오큐코어": "ocucor", "팔코어": "falcor", "바타코어": "battacor",
    "엑설지스": "exergis", "헬리오코어": "heliocor",
    "헤이트": "hate", "드레드": "dread", "디스페어": "despair",
    "워": "war", "브로큰워": "broken_war",
    "부르디": "burdi", "쉬브": "sheev", "쉬브": "sheev",
    # 모드/아케인 한글명
    "바이탈리티": "vitality", "바이탈리티": "vitality",
    "버서커 퓨리": "berserker_fury", "버서커 퓨리": "berserker_fury",
    "휠윈드": "whirlwind", "휠윈드": "whirlwind",
    "페이탈 엑셀러레이션": "fatal_acceleration",
    "컴버스천 빔": "combustion_beam",
    "블러드 러쉬": "blood_rush",
    "아케인 어벤저": "arcane_avenger",
    "아케인 에너자이즈": "arcane_energize",
    "아케인 그레이스": "arcane_grace",
    "아케인 가디언": "arcane_guardian",
    "컨디션 오버로드": "condition_overload",
    "어댑테이션": "adaptation",
    # 프라임 프레임 (시장 slug 없는 이름)
    "새린": "saryn", "나타": "nezha", "크로마": "chroma",
}

# 속성 한글 매핑
ELEMENT_KO = {
    "impact": "충격",
    "heat": "화염",
    "cold": "냉기",
    "electricity": "전기",
    "toxin": "독",
    "blast": "폭발",
    "radiation": "방사능",
    "gas": "가스",
    "magnetic": "자성",
    "viral": "바이러스",
    "corrosive": "부식",
}

# 속성 → 에페메라 이름
EPHEMERA_BY_ELEMENT = {
    "impact": "Impact Ephemera",
    "heat": "Vengeful Flame Ephemera",
    "cold": "Vengeful Chill Ephemera",
    "electricity": "Vengeful Charge Ephemera",
    "toxin": "Vengeful Toxin Ephemera",
    "radiation": "Vengeful Trickster Ephemera",
    "magnetic": "Vengeful Pull Ephemera",
}


async def _get(url: str) -> dict | None:
    """rate-limited GET. 공유 httpx client 사용."""
    async with _semaphore:
        try:
            client = get_client()
            r = await client.get(url, headers=_HEADERS)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            logger.error("경매 API HTTP %s: %s", e.response.status_code, url)
            return None
        except httpx.RequestError as e:
            logger.error("경매 API 요청 실패: %s — %s", url, e)
            return None
        finally:
            await asyncio.sleep(1 / MARKET_RATE_LIMIT)


# ── 리벤 경매 ──

async def search_riven_auctions(
    weapon_url_name: str = "",
    buyout_policy: str | None = None,
    sort_by: str = "price_asc",
    limit: int = 50,
) -> list[dict]:
    """리벤 모드 경매 검색.

    warframe.market 경매 API:
    GET /v1/auctions/search?type=riven
        &weapon_url_name=rubico
        &sort_by=price_asc
    """
    params = {
        "type": "riven",
        "sort_by": sort_by,
    }
    if buyout_policy:
        params["buyout_policy"] = buyout_policy
    if weapon_url_name:
        params["weapon_url_name"] = weapon_url_name

    url = f"{MARKET_API_BASE}/auctions/search?" + "&".join(
        f"{k}={v}" for k, v in params.items()
    )
    data = await _get(url)
    if not data:
        return []

    auctions = data.get("payload", {}).get("auctions", [])
    results = []

    for a in auctions[:limit]:
        item = a.get("item", {})
        owner = a.get("owner", {})

        # 리벤 옵션 파싱
        stats = []
        for attr in item.get("attributes", []):
            stats.append({
                "name": attr.get("url_name", "").replace("_", " "),
                "value": attr.get("value", 0),
                "positive": attr.get("positive", True),
            })

        results.append({
            "id": a.get("id", ""),
            "type": "riven",
            "weapon": item.get("weapon_url_name", "").replace("_", " ").title(),
            "weaponSlug": item.get("weapon_url_name", ""),
            "name": item.get("name", ""),
            "mastery": item.get("mastery_level", 0),
            "rerolls": item.get("re_rolls", 0),
            "polarity": item.get("polarity", ""),
            "modRank": item.get("mod_rank", 0),
            "stats": stats,
            "startingPrice": a.get("starting_price"),
            "buyoutPrice": a.get("buyout_price"),
            "topBid": a.get("top_bid"),
            "isDirectSell": a.get("is_direct_sell", False),
            "seller": owner.get("ingame_name", ""),
            "sellerStatus": owner.get("status", "offline"),
            "created": a.get("created", ""),
            "updated": a.get("updated", ""),
        })

    return results


# ── 리치/시스터 경매 ──

async def search_lich_auctions(
    weapon_url_name: str = "",
    element: str = "",
    ephemera: bool | None = None,  # None = 상관없음, True/False
    buyout_policy: str | None = None,
    sort_by: str = "price_asc",
    limit: int = 50,
) -> list[dict]:
    """리치/시스터 무기 경매 검색.

    GET /v1/auctions/search?type=lich
        &weapon_url_name=kuva_bramma
        &element=heat
        &having_ephemera=true
    """
    params = {
        "type": "lich",
        "sort_by": sort_by,
    }
    if buyout_policy:
        params["buyout_policy"] = buyout_policy
    if weapon_url_name:
        params["weapon_url_name"] = weapon_url_name
    if element:
        params["element"] = element
    if ephemera is not None:
        params["having_ephemera"] = "true" if ephemera else "false"

    url = f"{MARKET_API_BASE}/auctions/search?" + "&".join(
        f"{k}={v}" for k, v in params.items()
    )
    data = await _get(url)
    if not data:
        return []

    auctions = data.get("payload", {}).get("auctions", [])
    results = []

    for a in auctions[:limit]:
        item = a.get("item", {})
        owner = a.get("owner", {})

        # 리치인지 시스터인지 구분
        item_type = item.get("type", "")  # "lich" or "sister"
        element_key = item.get("element", "")
        has_ephemera = item.get("having_ephemera", False)
        bonus = item.get("damage", 0)  # 보너스 퍼센트

        ephemera_name = ""
        if has_ephemera and element_key:
            ephemera_name = EPHEMERA_BY_ELEMENT.get(element_key, "")

        results.append({
            "id": a.get("id", ""),
            "type": "lich",
            "weapon": item.get("weapon_url_name", "").replace("_", " ").title(),
            "weaponSlug": item.get("weapon_url_name", ""),
            "source": item_type or "lich",  # "lich" or "sister"
            "element": element_key,
            "elementKo": ELEMENT_KO.get(element_key, element_key),
            "bonus": round(bonus, 1),
            "ephemera": has_ephemera,
            "ephemeraName": ephemera_name,
            "startingPrice": a.get("starting_price"),
            "buyoutPrice": a.get("buyout_price"),
            "topBid": a.get("top_bid"),
            "isDirectSell": a.get("is_direct_sell", False),
            "seller": owner.get("ingame_name", ""),
            "sellerStatus": owner.get("status", "offline"),
            "created": a.get("created", ""),
            "updated": a.get("updated", ""),
        })

    return results


# ── 리벤 무기 목록 (자동완성용) ──

_riven_items_cache: list[dict] = []


async def get_riven_items() -> list[dict]:
    """리벤이 존재하는 무기 목록 (자동완성용). 캐싱됨."""
    global _riven_items_cache
    if _riven_items_cache:
        return _riven_items_cache

    data = await _get(f"{MARKET_API_BASE}/riven/items")
    if not data:
        return []

    items = data.get("payload", {}).get("items", [])
    _riven_items_cache = [
        {
            "url_name": item.get("url_name", ""),
            "item_name": item.get("item_name", ""),
            "riven_type": item.get("riven_type", ""),
            "group": item.get("group", ""),
        }
        for item in items
    ]
    logger.info("리벤 무기 목록 캐시: %d개", len(_riven_items_cache))
    return _riven_items_cache


async def _load_riven_ko_names():
    """리벤 무기 한글→영문 매핑 구축 (수동 매핑 + ko_names.json 활용)."""
    global _riven_ko_loaded
    if _riven_ko_loaded:
        return
    _riven_ko_loaded = True

    riven_items = await get_riven_items()
    if not riven_items:
        return

    # 리벤 url_name 세트
    riven_urls = {item["url_name"] for item in riven_items}

    # 1. 수동 매핑 등록
    for ko, en in _RIVEN_KO_MANUAL.items():
        if en in riven_urls:
            _riven_ko_to_en[ko.lower()] = en
            no_space = ko.replace(" ", "").lower()
            if no_space != ko.lower():
                _riven_ko_to_en[no_space] = en

    # 2. 기존 ko_names.json에서 리벤 무기에 해당하는 것 추출
    try:
        from src.market.items import _slug_to_ko
        for slug, ko_name in _slug_to_ko.items():
            # slug에서 _prime_set, _set 등 접미사 제거
            base = slug.replace("_prime_set", "").replace("_set", "")
            base = base.replace("_prime", "")
            if base in riven_urls:
                ko_base = ko_name.replace(" 프라임 세트", "").replace(" 세트", "")
                ko_base = ko_base.replace(" 프라임", "").strip()
                if ko_base:
                    _riven_ko_to_en[ko_base.lower()] = base
                    no_space = ko_base.replace(" ", "").lower()
                    if no_space != ko_base.lower():
                        _riven_ko_to_en[no_space] = base
    except ImportError:
        pass

    logger.info("리벤 한글 매핑 구축: %d개", len(_riven_ko_to_en))


async def resolve_riven_weapon(query: str) -> str:
    """사용자 입력(한글/영문/slug)을 리벤 무기 url_name으로 변환.

    1. 정확한 url_name 매칭
    2. 영문 item_name 매칭
    2.5. i18n 한글 이름 직접 매칭 (소벡, 글렉시온 등 일반 무기)
    3. 한글 이름 → slug → 리벤 url_name 매칭
    4. 퍼지 매칭 (부분 문자열 + SequenceMatcher)
    반환: url_name 또는 빈 문자열
    """
    items = await get_riven_items()
    if not items:
        return query  # 캐시 못 가져오면 원본 그대로

    # i18n 한글 매핑 로드 (최초 1회)
    await _load_riven_ko_names()

    q = query.strip().lower().replace(" ", "_")

    # 1. url_name 정확 일치
    for item in items:
        if item["url_name"] == q:
            return item["url_name"]

    # 2. 영문 item_name 정확 일치
    q_name = query.strip().lower()
    for item in items:
        if item["item_name"].lower() == q_name:
            return item["url_name"]

    # 2.5. i18n 한글 이름 직접 매칭 (소벡, 글렉시온 등 일반 무기 포함)
    q_no_space = query.replace(" ", "").lower()
    ko_match = _riven_ko_to_en.get(q_name) or _riven_ko_to_en.get(q_no_space)
    if ko_match:
        return ko_match

    # i18n 한글 부분 매칭 (퍼지)
    for ko_key, url_name in _riven_ko_to_en.items():
        if q_name in ko_key or ko_key in q_name:
            return url_name

    # 3. 한글 이름 → items.py의 매핑으로 slug 변환 → 리벤 url_name 매칭
    try:
        from src.market.items import _ko_to_slug, _slug_to_en_name
        q_no_space = query.replace(" ", "").lower()
        matched_slug = _ko_to_slug.get(q_name) or _ko_to_slug.get(q_no_space)
        if matched_slug:
            # slug에서 _prime, _set 등 접미사 제거하여 기본 무기명 추출
            en_name = _slug_to_en_name.get(matched_slug, matched_slug)
            en_base = en_name.lower().replace(" ", "_")
            for item in items:
                if item["url_name"] == en_base:
                    return item["url_name"]
            # prime 버전도 시도
            for item in items:
                if en_base.startswith(item["url_name"]) or item["url_name"].startswith(en_base):
                    return item["url_name"]
    except ImportError:
        pass

    # 4. 한글 퍼지매칭 — ko_to_slug 전체에서 비슷한 항목 찾기
    try:
        from src.market.items import _ko_to_slug, _slug_to_en_name
        q_no_space = query.replace(" ", "").lower()
        best_score = 0.0
        best_url = ""
        for ko_key, slug in _ko_to_slug.items():
            ko_clean = ko_key.replace(" ", "")
            if q_no_space in ko_clean or ko_clean in q_no_space:
                score = SequenceMatcher(None, q_no_space, ko_clean).ratio()
                if score > best_score:
                    en_name = _slug_to_en_name.get(slug, slug)
                    en_base = en_name.lower().replace(" ", "_")
                    # 정확 일치
                    for item in items:
                        if item["url_name"] == en_base:
                            best_score = score
                            best_url = item["url_name"]
                            break
                    else:
                        # slug에서 접미사 제거하여 기본 무기명 추출 후 prefix 매칭
                        for item in items:
                            if en_base.startswith(item["url_name"]) or item["url_name"].startswith(en_base):
                                if score > best_score:
                                    best_score = score
                                    best_url = item["url_name"]
                                break
        if best_url and best_score >= 0.5:
            return best_url
    except ImportError:
        pass

    # 5. 영문 퍼지 매칭 (부분 문자열)
    best_score = 0.0
    best_url = ""
    for item in items:
        name_lower = item["item_name"].lower()
        url = item["url_name"]
        if q_name in name_lower or name_lower in q_name:
            score = SequenceMatcher(None, q_name, name_lower).ratio()
            if score > best_score:
                best_score = score
                best_url = url
        elif q in url:
            score = SequenceMatcher(None, q, url).ratio()
            if score > best_score:
                best_score = score
                best_url = url

    if best_url and best_score >= 0.4:
        return best_url

    return query  # 못 찾으면 원본 그대로


# ── 리치/시스터 무기 목록 ──

_lich_items_cache: list[dict] = []


async def get_lich_items() -> list[dict]:
    """리치/시스터 무기 목록. 캐싱됨."""
    global _lich_items_cache
    if _lich_items_cache:
        return _lich_items_cache

    data = await _get(f"{MARKET_API_BASE}/lich/weapons")
    if not data:
        return []

    items = data.get("payload", {}).get("weapons", [])
    _lich_items_cache = [
        {
            "url_name": item.get("url_name", ""),
            "item_name": item.get("item_name", ""),
        }
        for item in items
    ]
    logger.info("리치/시스터 무기 목록 캐시: %d개", len(_lich_items_cache))
    return _lich_items_cache
