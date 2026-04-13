"""아이템명 한글↔영문 매핑 및 퍼지 검색."""

import json
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

# 커뮤니티 약칭/별명 → slug (공식 번역에 없는 표현만)
_KO_ALIASES: dict[str, str] = {
    "라이노프라임세트": "rhino_prime_set",
    "사르인프라임세트": "saryn_prime_set",
    "메사프라임세트": "mesa_prime_set",
    "볼트프라임세트": "volt_prime_set",
    "애쉬프라임세트": "ash_prime_set",
    "네크로스프라임세트": "nekros_prime_set",
    "노바프라임세트": "nova_prime_set",
    "네자프라임세트": "nezha_prime_set",
    # 모드 커뮤니티 별명
    "분열탄": "split_chamber",
    "맹렬한 돌풍": "condition_overload",
    "사냥꾼의 인내": "hunter_munitions",
}

# slug → 한글 이름 (공식 로컬라이제이션 + 별명)
_slug_to_ko: dict[str, str] = {}

# 한글 → slug 검색용 (공식 한글명 + 별명)
_ko_to_slug: dict[str, str] = {}

# 영문 이름 → slug 캐시 (API에서 로드)
_en_name_to_slug: dict[str, str] = {}
_slug_to_en_name: dict[str, str] = {}


def _load_ko_names() -> int:
    """공식 한국어 이름 매핑(ko_names.json) 로드."""
    ko_path = DATA_DIR / "ko_names.json"
    if not ko_path.exists():
        logger.warning("한글 이름 파일 없음: %s", ko_path)
        return 0
    try:
        mapping: dict[str, str] = json.loads(ko_path.read_text(encoding="utf-8"))
        for slug, ko_name in mapping.items():
            _slug_to_ko[slug] = ko_name
            _ko_to_slug[ko_name.lower()] = slug
            # 띄어쓰기 제거 버전도 등록
            no_space = ko_name.replace(" ", "").lower()
            if no_space != ko_name.lower():
                _ko_to_slug[no_space] = slug
        logger.info("한글 이름 로드: %d개", len(mapping))
        return len(mapping)
    except Exception:
        logger.exception("한글 이름 로드 실패")
        return 0


# 부품 slug 접미사 → 한글 (공식 게임 용어)
_PART_KO: dict[str, str] = {
    "blueprint": "블루프린트",
    "neuroptics_blueprint": "뉴로옵틱스",
    "chassis_blueprint": "섀시",
    "systems_blueprint": "시스템",
    "harness_blueprint": "하네스",
    "wings_blueprint": "윙",
    "barrel": "배럴",
    "receiver": "리시버",
    "reciever": "리시버",  # warframe.market 오타
    "stock": "스톡",
    "blade": "블레이드",
    "blades": "블레이드",
    "hilt": "힐트",
    "handle": "핸들",
    "grip": "그립",
    "guard": "가드",
    "head": "헤드",
    "string": "스트링",
    "upper_limb": "어퍼 림",
    "lower_limb": "로어 림",
    "link": "링크",
    "disc": "디스크",
    "band": "밴드",
    "buckle": "버클",
    "boot": "부츠",
    "gauntlet": "건틀릿",
    "ornament": "오너먼트",
    "pouch": "파우치",
    "stars": "스타",
    "chain": "체인",
    "carapace": "카라페이스",
    "cerebrum": "세레브럼",
    "systems": "시스템",
}


def _generate_part_ko_names() -> int:
    """세트 한글 이름 + 부품 접미사로 부품 한글 이름 자동 생성."""
    count = 0
    # _slug_to_ko에서 _set으로 끝나는 것들로부터 부품 이름 생성
    set_names = {slug: ko for slug, ko in _slug_to_ko.items() if slug.endswith("_set")}
    for set_slug, set_ko in set_names.items():
        base_slug = set_slug.rsplit("_set", 1)[0]  # "soma_prime"
        # "세트" 접미어 제거 → 기본 한글명
        base_ko = set_ko  # "소마 프라임" (세트 이름 자체가 "세트" 없이 저장됨)
        for part_suffix, part_ko in _PART_KO.items():
            part_slug = f"{base_slug}_{part_suffix}"
            if part_slug in _slug_to_ko:
                continue  # 이미 공식 번역이 있으면 스킵
            # items.json에 실제로 존재하는 slug만 (나중에 _load_items_cache에서 필터링됨)
            full_ko = f"{base_ko} {part_ko}"
            _slug_to_ko[part_slug] = full_ko
            _ko_to_slug[full_ko.lower()] = part_slug
            no_space = full_ko.replace(" ", "").lower()
            if no_space != full_ko.lower():
                _ko_to_slug[no_space] = part_slug
            count += 1
    return count


def _load_ko_aliases() -> None:
    """커뮤니티 별명 등록."""
    for alias, slug in _KO_ALIASES.items():
        _ko_to_slug[alias.lower()] = slug
        _ko_to_slug[alias.replace(" ", "").lower()] = slug


def _load_items_cache() -> bool:
    """로컬 캐시에서 아이템 목록 로드."""
    cache_path = DATA_DIR / "items.json"
    if not cache_path.exists():
        return False
    try:
        items = json.loads(cache_path.read_text(encoding="utf-8"))
        for item in items:
            slug = item["slug"]
            en_name = item.get("i18n", {}).get("en", {}).get("name", "")
            if en_name:
                _en_name_to_slug[en_name.lower()] = slug
                _slug_to_en_name[slug] = en_name
        logger.info("아이템 캐시 로드: %d개", len(_en_name_to_slug))
        return True
    except Exception:
        logger.exception("아이템 캐시 로드 실패")
        return False


# 모듈 로드 시 한글 이름 즉시 로드
_load_ko_names()
_generate_part_ko_names()
_load_ko_aliases()


async def refresh_items_cache() -> int:
    """API에서 아이템 목록을 가져와 캐시에 저장."""
    from src.market.api import fetch_all_items

    items = await fetch_all_items()
    if not items:
        return 0

    # 로컬 파일 저장
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / "items.json"
    cache_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    # 메모리 캐시 갱신
    _en_name_to_slug.clear()
    _slug_to_en_name.clear()
    for item in items:
        slug = item["slug"]
        en_name = item.get("i18n", {}).get("en", {}).get("name", "")
        if en_name:
            _en_name_to_slug[en_name.lower()] = slug
            _slug_to_en_name[slug] = en_name

    logger.info("아이템 캐시 갱신: %d개", len(_en_name_to_slug))
    return len(_en_name_to_slug)


async def refresh_ko_names() -> int:
    """WFCD i18n 데이터에서 한국어 이름을 갱신."""
    import httpx

    url = "https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/i18n.json"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            i18n_data: dict = resp.json()
    except Exception:
        logger.exception("WFCD i18n 다운로드 실패")
        return 0

    # items.json에서 gameRef → slug 매핑
    cache_path = DATA_DIR / "items.json"
    if not cache_path.exists():
        logger.warning("items.json 없음 — 한글 이름 갱신 불가")
        return 0

    items = json.loads(cache_path.read_text(encoding="utf-8"))
    ref_to_slug = {item["gameRef"]: item["slug"] for item in items if item.get("gameRef")}

    # 매핑 생성
    ko_map: dict[str, str] = {}
    for ref, translations in i18n_data.items():
        if ref in ref_to_slug:
            ko = translations.get("ko", {})
            if isinstance(ko, dict) and ko.get("name"):
                ko_map[ref_to_slug[ref]] = ko["name"]

    if not ko_map:
        return 0

    # 저장
    ko_path = DATA_DIR / "ko_names.json"
    ko_path.write_text(json.dumps(ko_map, ensure_ascii=False, indent=0), encoding="utf-8")

    # 메모리 갱신
    _slug_to_ko.clear()
    _ko_to_slug.clear()
    for slug, ko_name in ko_map.items():
        _slug_to_ko[slug] = ko_name
        _ko_to_slug[ko_name.lower()] = slug
        no_space = ko_name.replace(" ", "").lower()
        if no_space != ko_name.lower():
            _ko_to_slug[no_space] = slug
    _generate_part_ko_names()
    _load_ko_aliases()

    logger.info("한글 이름 갱신: %d개", len(ko_map))
    return len(ko_map)


@dataclass
class SearchResult:
    """아이템 검색 결과."""
    slug: str
    name: str       # 영문 이름
    score: float    # 0.0 ~ 1.0
    exact: bool = False
    ko_name: str = ""  # 한글 이름 (있으면)


def resolve_item(query: str) -> tuple[str, str] | None:
    """정확히 매칭되는 아이템 1개를 반환. 없으면 None."""
    results = search_items(query, limit=1)
    if results and results[0].score >= 0.55:
        return results[0].slug, results[0].name
    return None


def search_items(query: str, limit: int = 5) -> list[SearchResult]:
    """
    검색어에 대해 상위 후보 아이템을 반환한다.
    - 정확 일치 시 바로 반환 (score=1.0)
    - 부분 매칭 + 퍼지 매칭으로 후보 정렬
    """
    q = query.strip()
    if not q:
        return []

    # 캐시가 비어 있으면 로드 시도
    if not _en_name_to_slug:
        _load_items_cache()

    q_lower = q.lower()
    q_no_space = q.replace(" ", "").lower()

    # 1. 한글 정확 일치
    matched_slug = _ko_to_slug.get(q_lower) or _ko_to_slug.get(q_no_space)
    if matched_slug and matched_slug in _slug_to_en_name:
        return [SearchResult(
            slug=matched_slug, name=_slug_to_en_name[matched_slug],
            score=1.0, exact=True, ko_name=_slug_to_ko.get(matched_slug, ""),
        )]

    # 2. 영문 정확 일치
    if q_lower in _en_name_to_slug:
        slug = _en_name_to_slug[q_lower]
        return [SearchResult(slug=slug, name=_slug_to_en_name.get(slug, slug), score=1.0, exact=True, ko_name=_slug_to_ko.get(slug, ""))]

    # 3. slug 직접 일치
    q_slug = q_lower.replace(" ", "_")
    if q_slug in _slug_to_en_name:
        return [SearchResult(slug=q_slug, name=_slug_to_en_name[q_slug], score=1.0, exact=True, ko_name=_slug_to_ko.get(q_slug, ""))]

    # 4. 한글 부분 매칭 (API에 존재하는 아이템만)
    candidates: list[SearchResult] = []
    seen_slugs: set[str] = set()
    for ko_key, slug in _ko_to_slug.items():
        if slug not in _slug_to_en_name or slug in seen_slugs:
            continue
        # 부분 문자열 포함
        if q_no_space in ko_key.replace(" ", "") or ko_key.replace(" ", "") in q_no_space:
            score = SequenceMatcher(None, q_no_space, ko_key.replace(" ", "")).ratio()
            candidates.append(SearchResult(
                slug=slug, name=_slug_to_en_name[slug],
                score=max(score, 0.7), ko_name=_slug_to_ko.get(slug, ""),
            ))
            seen_slugs.add(slug)

    # 5. 한글 퍼지 매칭 (부분 매칭에서 못 찾은 경우)
    if len(candidates) < limit:
        for ko_key, slug in _ko_to_slug.items():
            if slug not in _slug_to_en_name or slug in seen_slugs:
                continue
            ko_clean = ko_key.replace(" ", "")
            score = SequenceMatcher(None, q_no_space, ko_clean).ratio()
            if score >= 0.5:
                candidates.append(SearchResult(
                    slug=slug, name=_slug_to_en_name[slug],
                    score=score, ko_name=_slug_to_ko.get(slug, ""),
                ))
                seen_slugs.add(slug)

    # 6. 영문 부분 매칭 + 퍼지 매칭
    for en_name, slug in _en_name_to_slug.items():
        if slug in seen_slugs:
            continue
        ko = _slug_to_ko.get(slug, "")
        # 부분 문자열 포함 (영문)
        if q_lower in en_name or en_name in q_lower:
            score = SequenceMatcher(None, q_lower, en_name).ratio()
            candidates.append(SearchResult(
                slug=slug, name=_slug_to_en_name.get(slug, slug), score=max(score, 0.7), ko_name=ko,
            ))
            seen_slugs.add(slug)
            continue
        # 퍼지 매칭
        score = SequenceMatcher(None, q_lower, en_name).ratio()
        if score >= 0.45:
            candidates.append(SearchResult(
                slug=slug, name=_slug_to_en_name.get(slug, slug), score=score, ko_name=ko,
            ))
            seen_slugs.add(slug)

    # 점수 순 정렬
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit]
