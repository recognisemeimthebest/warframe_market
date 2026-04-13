"""월드 상태 API — raw worldState.php 직접 파싱."""

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

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
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
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
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
                r = await c.get(_WS_URL)
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

async def get_arbitration() -> dict | None:
    await _load_mappings()
    ws = await _fetch_worldstate()
    if not ws:
        return None

    # 중재는 ExpiringKey 또는 별도 필드로 전달될 수 있음
    # 방법: SyndicateMissions에서 ArbitrationSyndicate 찾기
    now_ms = int(time.time() * 1000)

    for synd in ws.get("SyndicateMissions", []):
        tag = synd.get("Tag", "")
        if "Arbitration" not in tag and "arbiter" not in tag.lower():
            continue

        nodes = synd.get("Nodes", [])
        if not nodes:
            continue

        expiry_ms = _ts_to_ms(synd.get("Expiry", 0))
        node_id = nodes[0]
        return {
            "node": _node_name(node_id),
            "missionType": _node_mission_type(node_id),
            "enemy": _node_enemy(node_id),
            "eta": _eta_from_expiry(expiry_ms) if expiry_ms > now_ms else "",
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
