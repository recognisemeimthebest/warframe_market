"""워프레임 가상 모딩 계산기 — WFCD 오픈소스 데이터 기반."""

import asyncio
import json as _json
import logging
import re
from pathlib import Path

from src.http_client import get_client
from src.config import DATA_DIR

logger = logging.getLogger(__name__)

# ── 아케인 샤드 정적 데이터 ──────────────────────────────────────────────────

ARCHON_SHARDS: dict[str, dict] = {
    "crimson": {
        "name": "크림슨 샤드",
        "color": "#e53935",
        "options": [
            {"key": "ability_strength",  "label": "어빌리티 위력",   "std": 7.5,  "tau": 15.0, "type": "pct"},
            {"key": "casting_speed",     "label": "시전 속도",       "std": 10.0, "tau": 20.0, "type": "pct"},
            {"key": "buff_duration",     "label": "버프 지속 시간",  "std": 5.0,  "tau": 10.0, "type": "pct"},
            {"key": "health_flat",       "label": "체력 (고정)",     "std": 50.0, "tau": 100.0,"type": "flat"},
        ],
    },
    "azure": {
        "name": "애저 샤드",
        "color": "#1e88e5",
        "options": [
            {"key": "health_flat",  "label": "체력 (고정)",   "std": 150.0, "tau": 300.0, "type": "flat"},
            {"key": "shield_flat",  "label": "실드 (고정)",   "std": 150.0, "tau": 300.0, "type": "flat"},
            {"key": "armor_flat",   "label": "방어도 (고정)", "std": 75.0,  "tau": 150.0, "type": "flat"},
            {"key": "energy_flat",  "label": "에너지 (고정)", "std": 50.0,  "tau": 100.0, "type": "flat"},
        ],
    },
    "amber": {
        "name": "앰버 샤드",
        "color": "#fb8c00",
        "options": [
            {"key": "ability_duration", "label": "어빌리티 지속시간", "std": 12.5, "tau": 25.0, "type": "pct"},
            {"key": "parkour_speed",    "label": "파쿠르 속도",       "std": 10.0, "tau": 20.0, "type": "pct"},
            {"key": "energy_regen",     "label": "에너지 재생 (초당)", "std": 1.0,  "tau": 2.0,  "type": "flat_regen"},
        ],
    },
    "violet": {
        "name": "바이올렛 샤드",
        "color": "#8e24aa",
        "options": [
            {
                "key": "ability_strength_duration",
                "keys": ["ability_strength", "ability_duration"],
                "label": "어빌리티 위력 + 지속시간",
                "std": 7.5,
                "tau": 15.0,
                "type": "pct",
            },
        ],
    },
    "topaz": {
        "name": "토파즈 샤드",
        "color": "#f4511e",
        "options": [
            {"key": "overshield_flat",   "label": "오버실드 (고정)", "std": 150.0, "tau": 300.0, "type": "flat"},
            {"key": "status_chance_pct", "label": "상태이상 확률",   "std": 7.5,   "tau": 15.0,  "type": "pct"},
        ],
    },
    "emerald": {
        "name": "에메랄드 샤드",
        "color": "#43a047",
        "options": [
            {"key": "armor_flat",    "label": "방어도 (고정)",    "std": 75.0, "tau": 150.0, "type": "flat"},
            {"key": "buff_duration", "label": "버프 지속 시간",   "std": 5.0,  "tau": 10.0,  "type": "pct"},
        ],
    },
}

# ── 스탯 키 → 모드 텍스트 매핑 ─────────────────────────────────────────────

_MOD_STAT_MAP: dict[str, list[str]] = {
    "ability_strength":   ["Ability Strength"],
    "ability_duration":   ["Ability Duration"],
    "ability_range":      ["Ability Range"],
    "ability_efficiency": ["Ability Efficiency"],
    "health":             ["Health"],
    "shield":             ["Shield Capacity", "Max Shields"],
    "armor":              ["Armor"],
    "energy":             ["Energy Max", "Max Energy"],
    "sprint_speed":       ["Sprint Speed"],
}

# 역방향 매핑: 키워드 → stat_key (소문자 비교용)
_KEYWORD_TO_STAT: dict[str, str] = {}
for _stat_key, _keywords in _MOD_STAT_MAP.items():
    for _kw in _keywords:
        _KEYWORD_TO_STAT[_kw.lower()] = _stat_key

# ── 무기 모드 스탯 키 → 텍스트 매핑 ─────────────────────────────────────────

_WEAPON_MOD_STAT_MAP: dict[str, list[str]] = {
    "damage":          ["Damage", "Base Damage"],
    "multishot":       ["Multishot"],
    "crit_chance":     ["Critical Chance"],
    "crit_multiplier": ["Critical Damage"],
    "status_chance":   ["Status Chance"],
    "fire_rate":       ["Fire Rate", "Attack Speed"],
    "reload_speed":    ["Reload Speed"],
    "impact":          ["Impact"],
    "puncture":        ["Puncture"],
    "slash":           ["Slash"],
    "heat":            ["Heat"],
    "cold":            ["Cold"],
    "electricity":     ["Electricity"],
    "toxin":           ["Toxin"],
    "magnetic":        ["Magnetic"],
    "radiation":       ["Radiation"],
    "viral":           ["Viral"],
    "corrosive":       ["Corrosive"],
    "blast":           ["Blast"],
    "gas":             ["Gas"],
}

_WEAPON_KEYWORD_TO_STAT: dict[str, str] = {}
for _stat_key, _keywords in _WEAPON_MOD_STAT_MAP.items():
    for _kw in _keywords:
        _WEAPON_KEYWORD_TO_STAT[_kw.lower()] = _stat_key

# ── WFCD 캐시 경로 및 전역 ──────────────────────────────────────────────────

_WFCD_BASE = "https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json"
_WARFRAMES_PATH = Path(DATA_DIR) / "wf_warframes.json"
_MODS_PATH      = Path(DATA_DIR) / "wf_mods.json"
_ARCANES_PATH   = Path(DATA_DIR) / "wf_arcanes.json"

_warframes_cache: list[dict] = []
_mods_cache: list[dict] = []
_arcanes_cache: list[dict] = []
_cache_loaded = False
_cache_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """asyncio.Lock 지연 초기화 — 이벤트 루프가 생성된 이후 호출해야 한다."""
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


async def _download_and_save(url: str, path: Path) -> list[dict]:
    """URL에서 JSON 배열을 다운로드하여 로컬에 저장한 뒤 반환한다."""
    client = get_client()
    logger.info("WFCD 데이터 다운로드 중: %s", url)
    resp = await client.get(url, timeout=30.0)
    resp.raise_for_status()
    data: list[dict] = resp.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
    logger.info("WFCD 캐시 저장 완료: %s (%d개)", path.name, len(data))
    return data


async def _ensure_data() -> None:
    """WFCD 데이터가 로드되지 않았으면 로컬 캐시 또는 원격에서 로드한다."""
    global _cache_loaded, _warframes_cache, _mods_cache, _arcanes_cache

    if _cache_loaded:
        return

    async with _get_lock():
        # double-check inside lock
        if _cache_loaded:
            return

        all_local = (
            _WARFRAMES_PATH.exists()
            and _MODS_PATH.exists()
            and _ARCANES_PATH.exists()
        )

        if all_local:
            try:
                _warframes_cache = _json.loads(_WARFRAMES_PATH.read_text(encoding="utf-8"))
                _mods_cache      = _json.loads(_MODS_PATH.read_text(encoding="utf-8"))
                _arcanes_cache   = _json.loads(_ARCANES_PATH.read_text(encoding="utf-8"))
                logger.info(
                    "WFCD 로컬 캐시 로드: 워프레임 %d개, 모드 %d개, 아케인 %d개",
                    len(_warframes_cache), len(_mods_cache), len(_arcanes_cache),
                )
                _cache_loaded = True
                return
            except Exception:
                logger.warning("WFCD 로컬 캐시 파싱 실패 — 재다운로드", exc_info=True)

        # 원격 다운로드 (3개 병렬)
        try:
            results = await asyncio.gather(
                _download_and_save(f"{_WFCD_BASE}/Warframes.json", _WARFRAMES_PATH),
                _download_and_save(f"{_WFCD_BASE}/Mods.json",      _MODS_PATH),
                _download_and_save(f"{_WFCD_BASE}/Arcanes.json",    _ARCANES_PATH),
                return_exceptions=True,
            )
            wf_res, mod_res, arc_res = results

            _warframes_cache = wf_res if not isinstance(wf_res, BaseException) else []
            _mods_cache      = mod_res if not isinstance(mod_res, BaseException) else []
            _arcanes_cache   = arc_res if not isinstance(arc_res, BaseException) else []

            if isinstance(wf_res, BaseException):
                logger.error("워프레임 데이터 다운로드 실패: %s", wf_res)
            if isinstance(mod_res, BaseException):
                logger.error("모드 데이터 다운로드 실패: %s", mod_res)
            if isinstance(arc_res, BaseException):
                logger.error("아케인 데이터 다운로드 실패: %s", arc_res)

            _cache_loaded = True
        except Exception:
            logger.error("WFCD 데이터 초기화 실패 — graceful degradation", exc_info=True)
            _cache_loaded = True  # 빈 캐시라도 플래그 세팅해서 반복 시도 방지


def _parse_mod_effects(mod: dict, rank: int | None = None) -> dict[str, float]:
    """모드의 levelStats에서 스탯 효과를 파싱한다.

    Args:
        mod:  WFCD 모드 dict.
        rank: 추출할 랭크 인덱스. None이면 마지막(=최대) 랭크를 사용한다.

    Returns:
        ``{"ability_strength": 30.0, ...}`` 형태의 dict. 매핑 불가 항목은 제외.
    """
    level_stats: list[dict] = mod.get("levelStats", [])
    if not level_stats:
        return {}

    idx = -1 if rank is None else min(rank, len(level_stats) - 1)
    try:
        stats_at_rank: list[dict] = level_stats[idx].get("stats", [])
    except (IndexError, TypeError):
        return {}

    effects: dict[str, float] = {}
    # 예: "+30% Ability Strength" or "+0.2 Sprint Speed"
    _pattern = re.compile(r"([+\-][\d.]+)%?\s+(.*)", re.IGNORECASE)

    for stat_entry in stats_at_rank:
        text: str = stat_entry if isinstance(stat_entry, str) else str(stat_entry)
        m = _pattern.match(text.strip())
        if not m:
            continue
        value_str, label_raw = m.group(1), m.group(2).strip()
        try:
            value = float(value_str)
        except ValueError:
            continue

        label_lower = label_raw.lower()
        matched_key: str | None = None

        # 직접 매핑
        if label_lower in _KEYWORD_TO_STAT:
            matched_key = _KEYWORD_TO_STAT[label_lower]
        else:
            # 부분 문자열 매핑 (예: "ability strength" vs "Ability Strength")
            for kw, stat_key in _KEYWORD_TO_STAT.items():
                if kw in label_lower or label_lower in kw:
                    matched_key = stat_key
                    break

        if matched_key:
            effects[matched_key] = effects.get(matched_key, 0.0) + value

    return effects


# ── 검색 API ────────────────────────────────────────────────────────────────

# 워프레임 한글명 하드코딩 사전 (warframe.market에 기본형이 없는 워프레임 포함)
_WF_KO_NAMES: dict[str, str] = {
    "Ash":       "애쉬",       "Atlas":     "아틀라스",  "Banshee":   "밴시",
    "Baruuk":    "바루크",     "Caliban":   "칼리반",    "Chroma":    "크로마",
    "Citrine":   "시트린",     "Cyte-09":   "사이트-09", "Dagath":    "다가스",
    "Dante":     "단테",       "Ember":     "엠버",      "Equinox":   "이퀴녹스",
    "Excalibur": "엑스칼리버", "Follie":    "폴리",      "Frost":     "프로스트",
    "Gara":      "가라",       "Garuda":    "가루다",    "Gauss":     "가우스",
    "Grendel":   "그렌델",     "Gyre":      "자이어",    "Harrow":    "해로우",
    "Hildryn":   "힐드린",     "Hydroid":   "하이드로이드", "Inaros":  "이나로스",
    "Ivara":     "이바라",     "Jade":      "제이드",    "Khora":     "코라",
    "Koumei":    "코우메이",   "Kullervo":  "쿨레르보",  "Lavos":     "라보스",
    "Limbo":     "림보",       "Loki":      "로키",      "Mag":       "마그",
    "Mesa":      "메사",       "Mirage":    "미라쥬",    "Nekros":    "네크로스",
    "Nezha":     "나자",       "Nidus":     "나이더스",  "Nokko":     "노코",
    "Nova":      "노바",       "Nyx":       "닉스",      "Oberon":    "오베론",
    "Octavia":   "옥타비아",   "Oraxia":    "오락시아",  "Protea":    "프로테아",
    "Qorvex":    "코르벡스",   "Revenant":  "레버넌트",  "Rhino":     "라이노",
    "Saryn":     "사린",       "Sevagoth":  "세바고스",  "Styanax":   "스타이낙스",
    "Temple":    "템플",       "Titania":   "티타니아",  "Trinity":   "트리니티",
    "Uriel":     "우리엘",     "Valkyr":    "발키르",    "Vauban":    "보반",
    "Volt":      "볼트",       "Voruna":    "보루나",    "Wisp":      "위스프",
    "Wukong":    "오공",       "Xaku":      "자쿠",      "Yareli":    "야렐리",
    "Zephyr":    "제피르",
}


def _get_ko_warframe_name(base_name: str, has_prime: bool) -> str:
    """워프레임 영문 기본명을 한글명으로 조회한다.

    1순위: 하드코딩 사전 (빠르고 신뢰성 높음)
    2순위: warframe.market 프라임 세트 경유 역방향 매핑
    """
    # 1. 하드코딩 사전
    if base_name in _WF_KO_NAMES:
        return _WF_KO_NAMES[base_name]

    # 2. items.py 역방향 매핑 (프라임 세트 경유)
    try:
        from src.market.items import _en_name_to_slug, _slug_to_ko, _load_items_cache  # noqa: PLC0415
        if not _en_name_to_slug:
            _load_items_cache()

        if has_prime:
            slug = _en_name_to_slug.get((base_name + " prime set").lower(), "")
            if slug:
                ko = _slug_to_ko.get(slug, "")
                if ko:
                    return ko.replace(" 프라임 세트", "").replace(" 프라임", "").replace(" 세트", "")
    except Exception:
        pass
    return ""


async def get_warframe_grouped_list() -> list[dict]:
    """기본명으로 그룹화된 워프레임 목록을 반환한다.

    Returns:
        ``[{"name", "ko_name", "has_prime", "base": {...stats}, "prime": {...stats}|None}, ...]``
    """
    await _ensure_data()

    wf_by_name: dict[str, dict] = {
        wf.get("name", ""): wf for wf in _warframes_cache if wf.get("name")
    }

    def get_stats(wf: dict) -> dict:
        return {
            "health":      wf.get("health", 100),
            "shield":      wf.get("shield", 100),
            "armor":       wf.get("armor", 0),
            "power":       wf.get("power", 150),
            "sprintSpeed": wf.get("sprintSpeed", 1.0),
        }

    results: list[dict] = []
    seen: set[str] = set()

    for wf in _warframes_cache:
        name: str = wf.get("name", "")
        # 네크라멕 (MechSuits) 및 카테고리 없는 항목(헬민스 등) 제외 → 일반 워프레임만 포함
        if wf.get("productCategory") != "Suits":
            continue
        # 프라임·엄브라는 베이스 항목에서 처리
        if wf.get("isPrime", False) or name.endswith(" Umbra"):
            continue
        if name in seen:
            continue
        seen.add(name)

        prime_name = name + " Prime"
        has_prime = prime_name in wf_by_name
        umbra_name = name + " Umbra"

        ko_name = _get_ko_warframe_name(name, has_prime)

        entry: dict = {
            "name":      name,
            "ko_name":   ko_name or name,   # 한글 없으면 영문 그대로
            "has_prime": has_prime,
            "base":      get_stats(wf),
            "prime":     get_stats(wf_by_name[prime_name]) if has_prime else None,
        }
        if umbra_name in wf_by_name:
            entry["umbra"] = get_stats(wf_by_name[umbra_name])

        results.append(entry)

    results.sort(key=lambda x: x["ko_name"])
    return results


async def search_warframes(query: str, limit: int = 8) -> list[dict]:
    """이름으로 워프레임을 검색한다.

    Returns:
        ``[{"name", "health", "shield", "armor", "power", "sprintSpeed"}, ...]``
    """
    await _ensure_data()

    q = query.lower().strip()
    results: list[dict] = []

    for wf in _warframes_cache:
        name: str = wf.get("name", "")
        if q and q not in name.lower():
            continue
        results.append({
            "name":        name,
            "health":      wf.get("health", 100),
            "shield":      wf.get("shield", 100),
            "armor":       wf.get("armor", 0),
            "power":       wf.get("power", 150),
            "sprintSpeed": wf.get("sprintSpeed", 1.0),
        })

    # 완전 일치 우선, 그 다음 이름 길이 오름차순
    results.sort(key=lambda x: (x["name"].lower() != q, len(x["name"])))
    return results[:limit]


def _try_ko_to_en_mod(q: str) -> str:
    """한글 모드 쿼리를 영문명으로 변환 시도 (items.py 역방향 매핑 활용)."""
    try:
        from src.market.items import _ko_to_slug, _slug_to_en_name, _load_items_cache, _en_name_to_slug
        if not _en_name_to_slug:
            _load_items_cache()
        key_no_space = q.replace(" ", "").lower()
        slug = _ko_to_slug.get(key_no_space) or _ko_to_slug.get(q.lower())
        if slug:
            return _slug_to_en_name.get(slug, "")
    except Exception:
        pass
    return ""


async def search_mods(
    query: str, compat: str = "WARFRAME", limit: int = 12
) -> list[dict]:
    """이름과 호환 대상으로 모드를 검색한다.

    한글 쿼리는 items.py의 한글→슬러그→영문명 체인으로 변환 후 검색.

    Returns:
        ``[{"name", "polarity", "baseDrain", "fusionLimit", "effects", "maxRank"}, ...]``
    """
    await _ensure_data()

    q = query.lower().strip()

    # 한글 입력이면 영문명으로 변환 시도
    en_q = ""
    if q and any("\uAC00" <= c <= "\uD7A3" for c in q):
        en_q = _try_ko_to_en_mod(q).lower()

    results: list[dict] = []

    compat_upper = compat.upper()

    for mod in _mods_cache:
        name: str = mod.get("name", "")
        name_lower = name.lower()

        if q:
            match = (q in name_lower) or (en_q and en_q in name_lower)
            if not match:
                continue

        compat_name: str = (mod.get("compatName", "") or "").upper()
        is_exilus: bool   = bool(mod.get("isExilus", False))

        # 슬롯 유형별 필터
        if compat_upper == "AURA":
            # 오라 슬롯: AURA 전용
            if compat_name != "AURA":
                continue
        elif compat_upper == "EXILUS":
            # 엑실러스 슬롯: WARFRAME/ANY이면서 isExilus=True 인 모드만
            if compat_name not in {"WARFRAME", "ANY"}:
                continue
            if not is_exilus:
                continue
        else:
            # 일반 슬롯: WARFRAME/ANY 호환, 엑실러스 전용 모드 제외
            if compat_name not in {"WARFRAME", "ANY"}:
                continue
            if is_exilus:
                continue  # 엑실러스 모드는 엑실러스 슬롯에서만

        fusion_limit: int = mod.get("fusionLimit", 5)
        results.append({
            "name":        name,
            "polarity":    mod.get("polarity", ""),
            "baseDrain":   mod.get("baseDrain", 0),
            "fusionLimit": fusion_limit,
            "maxRank":     fusion_limit,
            "isExilus":    is_exilus,
            "effects":     _parse_mod_effects(mod),
        })

    results.sort(key=lambda x: x["name"])
    return results[:limit]


async def search_arcanes(query: str, limit: int = 10) -> list[dict]:
    """이름으로 아케인을 검색한다. 워프레임 관련 아케인만 반환한다.

    Returns:
        ``[{"name", "fusionLimit", "effects", "effectText"}, ...]``
    """
    await _ensure_data()

    q = query.lower().strip()
    results: list[dict] = []

    for arc in _arcanes_cache:
        name: str = arc.get("name", "")
        name_lower = name.lower()

        # 워프레임 관련 아케인 필터
        if not (
            "arcane" in name_lower
            or "molt" in name_lower
            or "magus" in name_lower
        ):
            continue

        if q and q not in name_lower:
            continue

        fusion_limit: int = arc.get("fusionLimit", 5)

        # 최대 랭크 스탯 텍스트 (계산 불가 효과도 표시용으로 수집)
        level_stats: list[dict] = arc.get("levelStats", [])
        effect_texts: list[str] = []
        if level_stats:
            try:
                last_stats = level_stats[-1].get("stats", [])
                effect_texts = [
                    s if isinstance(s, str) else str(s) for s in last_stats
                ]
            except (IndexError, TypeError):
                pass

        results.append({
            "name":        name,
            "fusionLimit": fusion_limit,
            "effects":     _parse_mod_effects(arc),
            "effectText":  " | ".join(effect_texts),
        })

    results.sort(key=lambda x: x["name"])
    return results[:limit]


# ── 스탯 계산 엔진 ───────────────────────────────────────────────────────────

def calc_warframe_stats(
    base: dict,
    mods: list[dict],
    shards: list[dict],
    arcanes: list[dict],
) -> dict:
    """모드 + 샤드 + 아케인을 적용하여 최종 워프레임 스탯을 계산한다.

    Args:
        base:    ``{"health", "shield", "armor", "power", "sprintSpeed"}``
        mods:    ``[{"effects": {stat_key: float}, "rank": int, "fusionLimit": int}, ...]``
        shards:  ``[{"color": str, "option_key": str, "tauforged": bool}, ...]`` (최대 5개)
        arcanes: ``[{"effects": {stat_key: float}}, ...]`` (최대 2개)

    Returns:
        ``{"health", "shield", "armor", "energy", "sprint",
           "strength", "duration", "range", "efficiency"}``
    """
    # ── 1. 모드 효과 누적 ─────────────────────────────────────────────────
    mod_bonuses: dict[str, float] = {k: 0.0 for k in _MOD_STAT_MAP}
    for m in mods:
        effects = m.get("effects", {})
        fusion_limit = max(m.get("fusionLimit", 5), 1)
        rank = m.get("rank", fusion_limit)
        ratio = rank / fusion_limit
        for k, v in effects.items():
            mod_bonuses[k] = mod_bonuses.get(k, 0.0) + v * ratio

    # ── 2. 샤드 효과 누적 ─────────────────────────────────────────────────
    shard_pct: dict[str, float] = {}
    shard_flat: dict[str, float] = {
        "health": 0.0, "shield": 0.0, "armor": 0.0,
        "energy": 0.0, "overshield": 0.0,
    }

    for s in shards:
        color   = s.get("color", "")
        opt_key = s.get("option_key", "")
        tau     = s.get("tauforged", False)
        shard_def = ARCHON_SHARDS.get(color, {})

        for opt in shard_def.get("options", []):
            # 다중 키(바이올렛) 지원 — opt_key가 keys 목록에 있거나 key 자체와 일치
            opt_keys: list[str] = opt.get("keys", [opt.get("key", "")])
            if opt_key != opt.get("key", "") and opt_key not in opt_keys:
                continue

            val: float = opt["tau"] if tau else opt["std"]
            opt_type: str = opt["type"]

            if opt_type == "pct":
                for k in opt_keys:
                    shard_pct[k] = shard_pct.get(k, 0.0) + val
            elif opt_type == "flat":
                for k in opt_keys:
                    # "health_flat" → "health", "shield_flat" → "shield" 등
                    flat_key = k.replace("_flat", "").replace("_pct", "")
                    shard_flat[flat_key] = shard_flat.get(flat_key, 0.0) + val
            # flat_regen은 에너지 재생이므로 별도 스탯 — 현재 계산기 범위 외

    # ── 3. 아케인 효과 누적 (max stack 가정) ──────────────────────────────
    arcane_bonuses: dict[str, float] = {k: 0.0 for k in _MOD_STAT_MAP}
    for a in arcanes:
        for k, v in a.get("effects", {}).items():
            arcane_bonuses[k] = arcane_bonuses.get(k, 0.0) + v

    # ── 4. 최종 스탯 계산 ─────────────────────────────────────────────────
    def pct(key: str) -> float:
        return (
            mod_bonuses.get(key, 0.0)
            + shard_pct.get(key, 0.0)
            + arcane_bonuses.get(key, 0.0)
        )

    health = base.get("health", 100) * (1 + pct("health") / 100) + shard_flat.get("health", 0.0)
    shield = base.get("shield", 100) * (1 + pct("shield") / 100) + shard_flat.get("shield", 0.0)
    armor  = base.get("armor",  0)   * (1 + pct("armor")  / 100) + shard_flat.get("armor",  0.0)
    energy = base.get("power",  150) * (1 + pct("energy") / 100) + shard_flat.get("energy", 0.0)
    sprint = base.get("sprintSpeed", 1.0) * (1 + pct("sprint_speed") / 100)

    strength   = 100.0 + pct("ability_strength")
    duration   = 100.0 + pct("ability_duration")
    ability_range     = 100.0 + pct("ability_range")
    efficiency = min(175.0, max(25.0, 100.0 + pct("ability_efficiency")))

    return {
        "health":     round(health),
        "shield":     round(shield),
        "armor":      round(armor),
        "energy":     round(energy),
        "sprint":     round(sprint, 2),
        "strength":   round(strength, 1),
        "duration":   round(duration, 1),
        "range":      round(ability_range, 1),
        "efficiency": round(efficiency, 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# ── 무기 모딩 ─────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

_PRIMARY_PATH   = Path(DATA_DIR) / "wf_primary.json"
_SECONDARY_PATH = Path(DATA_DIR) / "wf_secondary.json"
_MELEE_PATH     = Path(DATA_DIR) / "wf_melee.json"

_primary_cache:   list[dict] = []
_secondary_cache: list[dict] = []
_melee_cache:     list[dict] = []
_weapons_loaded = False

_WEAPON_TYPE_TO_COMPAT: dict[str, str] = {
    "Assault Rifle": "RIFLE",  "Rifle": "RIFLE",    "Beam Rifle": "RIFLE",
    "Launcher":      "RIFLE",  "Archgun": "RIFLE",
    "Shotgun":       "SHOTGUN",
    "Sniper Rifle":  "SNIPER",
    "Bow":           "BOW",    "Crossbow": "BOW",
    "Pistol":        "PISTOL", "Thrown":   "PISTOL", "Pistol Shotgun": "PISTOL",
    "Speargun":      "PISTOL",
}


async def _ensure_weapons_data() -> None:
    global _weapons_loaded, _primary_cache, _secondary_cache, _melee_cache
    if _weapons_loaded:
        return
    async with _get_lock():
        if _weapons_loaded:
            return
        all_local = _PRIMARY_PATH.exists() and _SECONDARY_PATH.exists() and _MELEE_PATH.exists()
        if all_local:
            try:
                _primary_cache   = _json.loads(_PRIMARY_PATH.read_text(encoding="utf-8"))
                _secondary_cache = _json.loads(_SECONDARY_PATH.read_text(encoding="utf-8"))
                _melee_cache     = _json.loads(_MELEE_PATH.read_text(encoding="utf-8"))
                logger.info(
                    "무기 로컬 캐시 로드: 주무기 %d개, 보조 %d개, 근접 %d개",
                    len(_primary_cache), len(_secondary_cache), len(_melee_cache),
                )
                _weapons_loaded = True
                return
            except Exception:
                logger.warning("무기 로컬 캐시 파싱 실패 — 재다운로드", exc_info=True)
        try:
            results = await asyncio.gather(
                _download_and_save(f"{_WFCD_BASE}/Primary.json",   _PRIMARY_PATH),
                _download_and_save(f"{_WFCD_BASE}/Secondary.json", _SECONDARY_PATH),
                _download_and_save(f"{_WFCD_BASE}/Melee.json",     _MELEE_PATH),
                return_exceptions=True,
            )
            pri_res, sec_res, mel_res = results
            _primary_cache   = pri_res if not isinstance(pri_res, BaseException) else []
            _secondary_cache = sec_res if not isinstance(sec_res, BaseException) else []
            _melee_cache     = mel_res if not isinstance(mel_res, BaseException) else []
            for label, res in [("주무기", pri_res), ("보조", sec_res), ("근접", mel_res)]:
                if isinstance(res, BaseException):
                    logger.error("%s 데이터 다운로드 실패: %s", label, res)
            _weapons_loaded = True
        except Exception:
            logger.error("무기 데이터 초기화 실패", exc_info=True)
            _weapons_loaded = True


def _parse_weapon_mod_effects(mod: dict, rank: int | None = None) -> dict[str, float]:
    level_stats: list[dict] = mod.get("levelStats", [])
    if not level_stats:
        return {}
    idx = -1 if rank is None else min(rank, len(level_stats) - 1)
    try:
        stats_at_rank: list[dict] = level_stats[idx].get("stats", [])
    except (IndexError, TypeError):
        return {}

    effects: dict[str, float] = {}
    _pattern = re.compile(r"([+\-][\d.]+)%?\s+(.*)", re.IGNORECASE)
    for stat_entry in stats_at_rank:
        text: str = stat_entry if isinstance(stat_entry, str) else str(stat_entry)
        m = _pattern.match(text.strip())
        if not m:
            continue
        value_str, label_raw = m.group(1), m.group(2).strip()
        try:
            value = float(value_str)
        except ValueError:
            continue
        label_lower = label_raw.lower()
        matched_key: str | None = None
        if label_lower in _WEAPON_KEYWORD_TO_STAT:
            matched_key = _WEAPON_KEYWORD_TO_STAT[label_lower]
        else:
            for kw, stat_key in _WEAPON_KEYWORD_TO_STAT.items():
                if kw in label_lower or label_lower in kw:
                    matched_key = stat_key
                    break
        if matched_key:
            effects[matched_key] = effects.get(matched_key, 0.0) + value
    return effects


def _get_weapon_base_stats(w: dict, weapon_type: str = "primary") -> dict:
    damage_obj = w.get("damage", {})
    if isinstance(damage_obj, dict):
        impact   = damage_obj.get("Impact",   damage_obj.get("impact",   0.0))
        puncture = damage_obj.get("Puncture", damage_obj.get("puncture", 0.0))
        slash    = damage_obj.get("Slash",    damage_obj.get("slash",    0.0))
        total    = sum(v for v in damage_obj.values() if isinstance(v, (int, float)))
    else:
        impact = puncture = slash = 0.0
        total = float(damage_obj or 0)
    fire_rate = w.get("fireRate") or w.get("attackSpeed") or 1.0
    return {
        "totalDamage":    round(total, 2),
        "impact":         round(impact, 2),
        "puncture":       round(puncture, 2),
        "slash":          round(slash, 2),
        "critChance":     round(w.get("criticalChance", 0.0), 4),
        "critMultiplier": round(w.get("criticalMultiplier", 1.5), 2),
        "statusChance":   round(w.get("statusChance", 0.0), 4),
        "fireRate":       round(fire_rate, 3),
        "magazineSize":   w.get("magazineSize", 0),
        "reloadTime":     round(w.get("reloadTime", 0.0), 2),
        "isMelee":        weapon_type == "melee",
    }


_WEAPON_SUFFIX_RE = re.compile(
    r'\s+(set|blueprint|receiver|barrel|stock|handle|guard|blade|grip|hilt|'
    r'string|limb|upper receiver|lower receiver|link|neuroptics|systems|chassis)\s*$',
    re.IGNORECASE,
)


def _try_ko_to_en_weapon(q: str) -> str:
    """한글 무기 쿼리를 영문명으로 변환 시도.

    warframe.market 아이템 캐시의 한글→슬러그→영문명 체인을 사용하고,
    " Set" 같은 접미사를 제거해 WFCD 이름과 맞춘다.
    """
    try:
        from src.market.items import _ko_to_slug, _slug_to_en_name, _load_items_cache, _en_name_to_slug  # noqa: PLC0415
        if not _en_name_to_slug:
            _load_items_cache()
        key_no_space = q.replace(" ", "").lower()
        slug = _ko_to_slug.get(key_no_space) or _ko_to_slug.get(q.lower())
        if slug:
            en_name = _slug_to_en_name.get(slug, "")
            if en_name:
                return _WEAPON_SUFFIX_RE.sub("", en_name).strip()
    except Exception:
        pass
    return ""


async def search_weapons(query: str, weapon_type: str = "primary", limit: int = 12) -> list[dict]:
    await _ensure_weapons_data()

    if weapon_type == "secondary":
        cache, default_compat = _secondary_cache, "PISTOL"
    elif weapon_type == "melee":
        cache, default_compat = _melee_cache, "MELEE"
    else:
        cache, default_compat = _primary_cache, "RIFLE"

    q = query.lower().strip()

    # 한글 입력이면 영문명으로 변환 시도
    en_q = ""
    if q and any("가" <= c <= "힣" for c in q):
        en_q = _try_ko_to_en_weapon(q).lower()

    results: list[dict] = []

    for w in cache:
        name: str = w.get("name", "")
        if not name:
            continue
        # 스킨/코스메틱 제외
        if w.get("productCategory") in {"SkinSet", "Appearance"}:
            continue
        if "skin" in name.lower() and "skin" not in q:
            continue
        if q:
            name_lower = name.lower()
            if not ((q in name_lower) or (en_q and en_q in name_lower)):
                continue

        wtype = w.get("type", "")
        compat = _WEAPON_TYPE_TO_COMPAT.get(wtype, default_compat)

        results.append({
            "name":   name,
            "type":   wtype,
            "compat": compat,
            **_get_weapon_base_stats(w, weapon_type),
        })

    results.sort(key=lambda x: (x["name"].lower() != q, len(x["name"]), x["name"]))
    return results[:limit]


async def search_weapon_mods(query: str, compat: str = "RIFLE", limit: int = 12) -> list[dict]:
    await _ensure_data()  # _mods_cache 사용

    q = query.lower().strip()
    en_q = ""
    if q and any("가" <= c <= "힣" for c in q):
        en_q = _try_ko_to_en_mod(q).lower()

    compat_upper = compat.upper()
    compat_allowed = {compat_upper, "ANY"}
    if compat_upper in {"SHOTGUN", "SNIPER", "BOW"}:
        compat_allowed.add("RIFLE")

    results: list[dict] = []
    for mod in _mods_cache:
        name: str = mod.get("name", "")
        name_lower = name.lower()
        if q:
            if not ((q in name_lower) or (en_q and en_q in name_lower)):
                continue
        mod_compat: str = (mod.get("compatName", "") or "").upper()
        if mod_compat not in compat_allowed:
            continue
        fusion_limit: int = mod.get("fusionLimit", 5)
        results.append({
            "name":        name,
            "polarity":    mod.get("polarity", ""),
            "baseDrain":   mod.get("baseDrain", 0),
            "fusionLimit": fusion_limit,
            "maxRank":     fusion_limit,
            "isExilus":    bool(mod.get("isExilus", False)),
            "effects":     _parse_weapon_mod_effects(mod),
        })

    results.sort(key=lambda x: x["name"])
    return results[:limit]


def calc_weapon_stats(base: dict, mods: list[dict]) -> dict:
    bonuses: dict[str, float] = {k: 0.0 for k in _WEAPON_MOD_STAT_MAP}
    for m in mods:
        effects = m.get("effects", {})
        fusion_limit = max(m.get("fusionLimit", 5), 1)
        rank = m.get("rank", fusion_limit)
        ratio = rank / fusion_limit
        for k, v in effects.items():
            bonuses[k] = bonuses.get(k, 0.0) + v * ratio

    base_total    = base.get("totalDamage", 50.0)
    base_impact   = base.get("impact", 0.0)
    base_puncture = base.get("puncture", 0.0)
    base_slash    = base.get("slash", 0.0)
    base_fr       = base.get("fireRate", 1.0)
    base_cc       = base.get("critChance", 0.0)
    base_cm       = base.get("critMultiplier", 1.5)
    base_sc       = base.get("statusChance", 0.0)

    # 물리 데미지
    dmg_mult   = 1 + bonuses["damage"] / 100
    imp_mult   = 1 + bonuses["impact"] / 100
    pun_mult   = 1 + bonuses["puncture"] / 100
    sla_mult   = 1 + bonuses["slash"] / 100
    final_imp  = base_impact   * imp_mult * dmg_mult
    final_pun  = base_puncture * pun_mult * dmg_mult
    final_sla  = base_slash    * sla_mult * dmg_mult
    final_phy  = final_imp + final_pun + final_sla

    # 원소 데미지 (기본 총 데미지의 %)
    elemental: dict[str, float] = {}
    for elem in ("heat", "cold", "electricity", "toxin",
                 "magnetic", "radiation", "viral", "corrosive", "blast", "gas"):
        val = bonuses.get(elem, 0.0)
        if val:
            elemental[elem] = round(base_total * val / 100, 1)
    total_elemental = sum(elemental.values())
    final_total = final_phy + total_elemental

    final_cc = min(1.0, base_cc * (1 + bonuses["crit_chance"] / 100))
    final_cm = base_cm * (1 + bonuses["crit_multiplier"] / 100)
    final_sc = min(1.0, base_sc * (1 + bonuses["status_chance"] / 100))
    final_fr = base_fr * (1 + bonuses["fire_rate"] / 100)
    multishot = 1 + bonuses["multishot"] / 100

    # 예상 DPS (단순 추정)
    avg_crit = 1 + final_cc * (final_cm - 1)
    dps = final_total * final_fr * multishot * avg_crit

    return {
        "totalDamage":    round(final_total, 1),
        "physicalDamage": round(final_phy, 1),
        "impact":         round(final_imp, 1),
        "puncture":       round(final_pun, 1),
        "slash":          round(final_sla, 1),
        "elemental":      elemental,
        "critChance":     round(final_cc * 100, 1),
        "critMultiplier": round(final_cm, 2),
        "statusChance":   round(final_sc * 100, 1),
        "fireRate":       round(final_fr, 3),
        "multishot":      round(multishot, 2),
        "dps":            round(dps, 0),
    }
