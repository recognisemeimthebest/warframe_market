"""월드 상태 API — raw worldState.php 직접 파싱."""

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from src.http_client import get_client

logger = logging.getLogger(__name__)

_WS_URL = "https://content.warframe.com/dynamic/worldState.php"
_TIMEOUT = 20.0
_semaphore = asyncio.Semaphore(2)

# ── 매핑 데이터 (GitHub에서 로드) ──
_sol_nodes: dict = {}
_mission_types: dict = {}
_fissure_mods: dict = {}
_faction_map = {
    "FC_GRINEER": "Grineer", "FC_CORPUS": "Corpus",
    "FC_INFESTATION": "Infested", "FC_CORRUPTED": "Corrupted",
    "FC_OROKIN": "Orokin", "FC_SENTIENT": "Sentient",
}
_item_name_cache: dict = {}

_mapping_loaded = False


async def _load_mappings():
    """WFCD warframe-worldstate-data에서 매핑 로드."""
    global _sol_nodes, _mission_types, _fissure_mods, _mapping_loaded
    if _mapping_loaded:
        return

    base = "https://raw.githubusercontent.com/WFCD/warframe-worldstate-data/master/data"
    c = get_client()
    try:
        r1, r2, r3 = await asyncio.gather(
            c.get(f"{base}/solNodes.json"),
            c.get(f"{base}/missionTypes.json"),
            c.get(f"{base}/fissureModifiers.json"),
        )
        _sol_nodes = r1.json()
        _mission_types = r2.json()
        _fissure_mods = r3.json()
        _mapping_loaded = True
        logger.info("월드 매핑 로드: nodes=%d, missions=%d, fissures=%d",
                    len(_sol_nodes), len(_mission_types), len(_fissure_mods))
    except Exception:
        logger.warning("월드 매핑 로드 실패", exc_info=True)


async def _fetch_worldstate() -> dict | None:
    """raw worldState 다운로드."""
    async with _semaphore:
        try:
            client = get_client()
            r = await client.get(_WS_URL, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception:
            logger.error("worldState 다운로드 실패", exc_info=True)
            return None


def _node_name(node_id: str) -> str:
    """노드 ID → 읽기 좋은 이름."""
    info = _sol_nodes.get(node_id)
    if info:
        return info.get("value", node_id)
    return node_id


def _node_enemy(node_id: str) -> str:
    info = _sol_nodes.get(node_id)
    if info:
        return info.get("enemy", "")
    return ""


def _node_mission_type(node_id: str) -> str:
    info = _sol_nodes.get(node_id)
    if info:
        return info.get("type", "")
    return ""


def _mission_type_name(mt: str) -> str:
    info = _mission_types.get(mt)
    if info:
        return info.get("value", mt)
    return mt.replace("MT_", "").replace("_", " ").title()


def _faction_name(fc: str) -> str:
    return _faction_map.get(fc, fc.replace("FC_", "").title())


def _ts_to_ms(obj) -> int:
    """MongoDB 타임스탬프 → ms."""
    if isinstance(obj, dict):
        d = obj.get("$date", obj)
        if isinstance(d, dict):
            return int(d.get("$numberLong", 0))
        return int(d)
    return int(obj)


def _eta_from_expiry(expiry_ms: int) -> str:
    """남은 시간 문자열."""
    now_ms = int(time.time() * 1000)
    diff = max(0, expiry_ms - now_ms)
    mins = diff // 60000
    if mins >= 60:
        return f"{mins // 60}시간 {mins % 60}분"
    return f"{mins}분"


# ── 균열 (Fissures) ──

async def get_fissures() -> list[dict]:
    await _load_mappings()
    ws = await _fetch_worldstate()
    if not ws:
        return []

    now_ms = int(time.time() * 1000)
    results = []

    for m in ws.get("ActiveMissions", []):
        expiry_ms = _ts_to_ms(m.get("Expiry", 0))
        if expiry_ms < now_ms:
            continue

        modifier = m.get("Modifier", "")
        tier_info = _fissure_mods.get(modifier, {})
        tier = tier_info.get("value", modifier)
        tier_num = tier_info.get("num", 0)
        node_id = m.get("Node", "")
        is_hard = m.get("Hard", False)

        results.append({
            "node": _node_name(node_id),
            "missionType": _node_mission_type(node_id) or _mission_type_name(m.get("MissionType", "")),
            "tier": tier,
            "tierNum": tier_num,
            "enemy": _node_enemy(node_id),
            "isHard": is_hard,
            "isStorm": m.get("IsStorm", False),
            "eta": _eta_from_expiry(expiry_ms),
        })

    tier_order = {"Lith": 1, "Meso": 2, "Neo": 3, "Axi": 4, "Requiem": 5, "Omnia": 6}
    results.sort(key=lambda x: (x["isHard"], tier_order.get(x["tier"], 9)))
    return results


# ── 중재 (Arbitration) ──
# worldState의 ArbitersSyndicate 블록에서 직접 계산.
# 7개 노드를 1시간마다 순환하며, 24시간마다 DE가 새 블록을 제공한다.
# (activation 기준 경과 시간 // 3600) % 노드 수 = 현재 인덱스

async def get_arbitration() -> dict | None:
    await _load_mappings()
    ws = await _fetch_worldstate()
    if not ws:
        return None

    now_ms = int(time.time() * 1000)
    now_sec = now_ms // 1000

    for synd in ws.get("SyndicateMissions", []):
        if synd.get("Tag", "") != "ArbitersSyndicate":
            continue

        nodes = synd.get("Nodes", [])
        if not nodes:
            return None

        act_ms = _ts_to_ms(synd.get("Activation", 0))
        exp_ms = _ts_to_ms(synd.get("Expiry", 0))
        if exp_ms <= now_ms:
            return None  # 블록 만료

        act_sec = act_ms // 1000
        elapsed_sec = now_sec - act_sec
        idx = (elapsed_sec // 3600) % len(nodes)
        node_id = nodes[idx]

        # 현재 노드가 교체되기까지 남은 시간
        secs_into_slot = elapsed_sec % 3600
        remaining_sec = 3600 - secs_into_slot
        eta = f"{remaining_sec // 60}분"

        return {
            "node": _node_name(node_id),
            "missionType": _node_mission_type(node_id),
            "enemy": _node_enemy(node_id),
            "eta": eta,
        }

    return None


# ── 침공 (Invasions) ──

async def get_invasions() -> list[dict]:
    await _load_mappings()
    ws = await _fetch_worldstate()
    if not ws:
        return []

    results = []
    for inv in ws.get("Invasions", []):
        if inv.get("Completed"):
            continue

        node_id = inv.get("Node", "")
        count = inv.get("Count", 0)
        goal = inv.get("Goal", 1)
        completion = round((count + goal) / (goal * 2) * 100, 1) if goal else 0

        atk_reward = _parse_reward(inv.get("AttackerReward"))
        def_reward = _parse_reward(inv.get("DefenderReward"))

        results.append({
            "node": _node_name(node_id),
            "desc": inv.get("LocTag", "").split("/")[-1].replace("Generic", ""),
            "attackingFaction": _faction_name(inv.get("Faction", "")),
            "defendingFaction": _faction_name(inv.get("DefenderFaction", "")),
            "attackerReward": atk_reward,
            "defenderReward": def_reward,
            "vsInfestation": inv.get("Faction") == "FC_INFESTATION",
            "completion": completion,
            "eta": "",
        })

    return results


def _parse_reward(reward_data) -> dict:
    if not reward_data:
        return {"items": [], "credits": 0}
    items = []
    for item in reward_data.get("countedItems", []):
        item_type = item.get("ItemType", "")
        # 아이템 경로에서 이름 추출
        name = item_type.split("/")[-1]
        # CamelCase → 읽기 좋게
        import re
        name = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
        name = name.replace("Blueprint", " Blueprint").strip()
        items.append({
            "name": name,
            "count": item.get("ItemCount", 1),
        })
    return {
        "items": items,
        "credits": reward_data.get("credits", 0),
    }


# ── 오픈월드 사이클 (epoch 계산) ──

async def get_cycles() -> dict:
    now_ms = int(time.time() * 1000)
    result = {}

    # 세투스 (Plains of Eidolon): 150분 사이클, 100분 낮 + 50분 밤
    CETUS_EPOCH = 1510444800000
    cetus_cycle = 150 * 60 * 1000
    cetus_day = 100 * 60 * 1000
    cetus_pos = (now_ms - CETUS_EPOCH) % cetus_cycle
    is_day = cetus_pos < cetus_day
    cetus_left = (cetus_day - cetus_pos) if is_day else (cetus_cycle - cetus_pos)
    result["cetus"] = {
        "state": "day" if is_day else "night",
        "timeLeft": f"{cetus_left // 60000}분",
    }

    # 오브 밸리스 (Orb Vallis): 20분 사이클, 6분 40초 따뜻 + 13분 20초 추움
    VALLIS_EPOCH = 1541837628000
    vallis_cycle = 20 * 60 * 1000
    vallis_warm = 400 * 1000  # 6분 40초
    vallis_pos = (now_ms - VALLIS_EPOCH) % vallis_cycle
    is_warm = vallis_pos < vallis_warm
    vallis_left = (vallis_warm - vallis_pos) if is_warm else (vallis_cycle - vallis_pos)
    result["vallis"] = {
        "state": "warm" if is_warm else "cold",
        "timeLeft": f"{vallis_left // 60000}분",
    }

    # 캠비온 퇴적지 (Cambion Drift): 50분 사이클, 25분 fass + 25분 vome
    CAMBION_EPOCH = 1609459200000
    cambion_cycle = 50 * 60 * 1000
    cambion_half = 25 * 60 * 1000
    cambion_pos = (now_ms - CAMBION_EPOCH) % cambion_cycle
    is_fass = cambion_pos < cambion_half
    cambion_left = (cambion_half - cambion_pos) if is_fass else (cambion_cycle - cambion_pos)
    result["cambion"] = {
        "state": "fass" if is_fass else "vome",
        "timeLeft": f"{cambion_left // 60000}분",
    }

    # 자리만 (Zariman): 데이터가 raw worldstate에서 제공될 수 있음
    # 간단하게 corpus/grineer 사이클 (150분)
    ZARIMAN_EPOCH = 1651795200000
    zariman_cycle = 150 * 60 * 1000
    zariman_half = 75 * 60 * 1000
    zariman_pos = (now_ms - ZARIMAN_EPOCH) % zariman_cycle
    is_corpus = zariman_pos < zariman_half
    zariman_left = (zariman_half - zariman_pos) if is_corpus else (zariman_cycle - zariman_pos)
    result["zariman"] = {
        "state": "corpus" if is_corpus else "grineer",
        "timeLeft": f"{zariman_left // 60000}분",
    }

    return result


# ── 전체 월드 상태 ──

async def get_world_state() -> dict:
    fissures, arbitration, invasions, cycles = await asyncio.gather(
        get_fissures(),
        get_arbitration(),
        get_invasions(),
        get_cycles(),
    )
    return {
        "fissures": fissures,
        "arbitration": arbitration,
        "invasions": invasions,
        "cycles": cycles,
    }


# ── 상인 / 진영 ──

_WFSTAT_URL = "https://api.warframestat.us/pc"


async def get_void_trader() -> dict:
    """키티어 (보이드 상인) 현재 재고."""
    try:
        client = get_client()
        r = await client.get(f"{_WFSTAT_URL}/voidTrader")
        r.raise_for_status()
        d = r.json()
    except Exception:
        logger.exception("키티어 데이터 조회 실패")
        return {"active": False, "error": True}

    def _iso_to_ms(s) -> int:
        if not s:
            return 0
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0

    now_ms = int(time.time() * 1000)
    activation_ms = _iso_to_ms(d.get("activation"))
    expiry_ms = _iso_to_ms(d.get("expiry"))
    active = activation_ms <= now_ms < expiry_ms

    inventory = []
    for item in d.get("inventory", []):
        inventory.append({
            "item": item.get("item", ""),
            "ducats": item.get("ducats", 0),
            "credits": item.get("credits", 0),
        })

    return {
        "active": active,
        "location": d.get("location", ""),
        "eta": _eta_from_expiry(expiry_ms) if active else _eta_from_expiry(activation_ms),
        "eta_label": "출발까지" if active else "도착까지",
        "inventory": inventory,
    }


async def get_steel_path() -> dict:
    """테신 스틸패스 스토어."""
    try:
        client = get_client()
        r = await client.get(f"{_WFSTAT_URL}/steelPath")
        r.raise_for_status()
        d = r.json()
    except Exception:
        logger.exception("스틸패스 데이터 조회 실패")
        return {"error": True}

    return {
        "current_reward": d.get("currentReward", {}),
        "remaining": d.get("remaining", ""),
        "rotation": d.get("rotation", []),
        "evergreens": d.get("evergreens", []),
    }


# ── 인카논 제네시스 로테이션 ──

async def get_incarnon_rotation(search: str = "", weeks: int = 9) -> dict:
    """인카논 제네시스 어댑터 주간 로테이션 반환.

    worldState에서 현재 주차를 실시간으로 가져와 로테이션 인덱스를 보정.
    """
    from src.world.incarnon import (
        INCARNON_ROTATION, get_rotation_schedule, find_weapon,
        _current_week_idx, _EPOCH_UNIX, _EPOCH_ROTATION_IDX, _WEEK_SECS,
    )
    import src.world.incarnon as _inc

    # 1. worldState에서 현재 주차 실시간 조회 (보정용)
    live_weapons: list[str] = []
    try:
        ws = await _fetch_worldstate()
        if ws:
            schedule = ws.get("EndlessXpSchedule", [])
            if schedule:
                for cat in schedule[0].get("CategoryChoices", []):
                    if cat.get("Category") == "EXC_HARD":
                        live_weapons = cat.get("Choices", [])
                        break
    except Exception:
        logger.warning("인카논 실시간 데이터 조회 실패", exc_info=True)

    # 2. 실시간 데이터와 하드코딩 로테이션 대조 → 인덱스 보정
    if live_weapons:
        live_set = {w.lower() for w in live_weapons}
        for idx, rotation_week in enumerate(INCARNON_ROTATION):
            rot_set = {w.lower() for w in rotation_week}
            if len(live_set & rot_set) >= 3:   # 3개 이상 일치 시 해당 인덱스 사용
                # 에포크 기반 계산과 다르면 동적으로 오버라이드
                elapsed_weeks = int((time.time() - _EPOCH_UNIX) // _WEEK_SECS)
                expected_idx = (_EPOCH_ROTATION_IDX + elapsed_weeks) % len(INCARNON_ROTATION)
                if expected_idx != idx:
                    logger.warning("인카논 로테이션 인덱스 보정: %d → %d", expected_idx, idx)
                    # 에포크를 동적으로 조정 (이번 주차가 idx임을 기준으로 재계산)
                    _inc._EPOCH_ROTATION_IDX = idx
                    _inc._EPOCH_UNIX = int(time.time()) - (elapsed_weeks * _WEEK_SECS)
                break

    # 3. 특정 무기 검색
    if search.strip():
        found = find_weapon(search)
        if found:
            weeks_left = found["week_offset"]
            if weeks_left == 0:
                msg = "이번 주에 왔어요!"
            elif weeks_left == 1:
                msg = "다음 주에 와요."
            else:
                msg = f"{weeks_left}주 후에 와요."
            return {
                "mode": "search",
                "weapon": found["weapon"],
                "week_offset": weeks_left,
                "start_date": found["start_date"],
                "all_weapons": found["all_weapons"],
                "message": msg,
                "schedule": get_rotation_schedule(weeks),
                "live_weapons": live_weapons,
            }
        return {
            "mode": "search",
            "weapon": None,
            "message": f'"{search}" 인카논은 목록에 없어요. 이름을 확인해주세요.',
            "schedule": get_rotation_schedule(weeks),
            "live_weapons": live_weapons,
        }

    return {
        "mode": "schedule",
        "schedule": get_rotation_schedule(weeks),
        "live_weapons": live_weapons,
    }
