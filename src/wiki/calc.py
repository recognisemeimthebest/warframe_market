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

    for mod in _mods_cache:
        name: str = mod.get("name", "")
        name_lower = name.lower()

        if q:
            match = (q in name_lower) or (en_q and en_q in name_lower)
            if not match:
                continue

        compat_name: str = mod.get("compatName", "") or ""
        # 워프레임 호환: WARFRAME, ANY, AURA
        if compat == "WARFRAME":
            allowed = {"WARFRAME", "ANY", "AURA"}
        else:
            allowed = {compat.upper(), "ANY"}

        if compat_name.upper() not in allowed:
            continue

        fusion_limit: int = mod.get("fusionLimit", 5)
        results.append({
            "name":        name,
            "polarity":    mod.get("polarity", ""),
            "baseDrain":   mod.get("baseDrain", 0),
            "fusionLimit": fusion_limit,
            "maxRank":     fusion_limit,
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
