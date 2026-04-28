"""바로 키티어 — 히스토리 DB + Lua 스크래핑 + 피처 매트릭스."""

import asyncio
import logging
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.config import DATA_DIR
from src.http_client import get_client

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "baro.db"
_FANDOM_API = "https://warframe.fandom.com/api.php"
_WFSTAT_BARO = "https://api.warframestat.us/pc/voidTrader"

# 첫 방문: 2015-08-07, 이후 약 14일 간격
_FIRST_VISIT_EPOCH = datetime(2015, 8, 7, tzinfo=timezone.utc)

FEATURE_NAMES = [
    "visits_since_last",
    "avg_interval",
    "std_interval",
    "overdue_ratio",
    "appearances_so_far",
    "appearance_rate",
    "log_ducat",
    "item_type_enc",
]


@dataclass
class BaroItemMeta:
    item_name: str
    ducat_cost: int
    credit_cost: int
    item_type: str
    pc_offering_dates: list[str] = field(default_factory=list)


# ── DB 초기화 ──────────────────────────────────────────────────────────────────

def init_baro_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS baro_visits (
                visit_num   INTEGER PRIMARY KEY,
                visit_date  TEXT NOT NULL,
                location    TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS baro_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name   TEXT NOT NULL UNIQUE,
                ducat_cost  INTEGER DEFAULT 0,
                credit_cost INTEGER DEFAULT 0,
                item_type   TEXT DEFAULT 'Unknown'
            );

            CREATE TABLE IF NOT EXISTS baro_appearances (
                item_id   INTEGER REFERENCES baro_items(id),
                visit_num INTEGER REFERENCES baro_visits(visit_num),
                PRIMARY KEY (item_id, visit_num)
            );

            CREATE INDEX IF NOT EXISTS idx_app_item  ON baro_appearances(item_id);
            CREATE INDEX IF NOT EXISTS idx_app_visit ON baro_appearances(visit_num);
        """)


def get_db_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        visits   = conn.execute("SELECT COUNT(*) FROM baro_visits").fetchone()[0]
        items    = conn.execute("SELECT COUNT(*) FROM baro_items").fetchone()[0]
        appears  = conn.execute("SELECT COUNT(*) FROM baro_appearances").fetchone()[0]
        last     = conn.execute(
            "SELECT MAX(visit_num), MAX(visit_date) FROM baro_visits"
        ).fetchone()
    return {
        "total_visits": visits,
        "total_items": items,
        "total_appearances": appears,
        "last_visit_num": last[0],
        "last_visit_date": last[1],
    }


# ── 날짜 ↔ 방문번호 ────────────────────────────────────────────────────────────

def date_to_visit_num(date_str: str) -> int:
    """ISO 날짜 → 방문 번호 (2015-08-07 기준 14일 단위)."""
    try:
        d = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        delta = (d - _FIRST_VISIT_EPOCH).days
        return max(1, round(delta / 14) + 1)
    except Exception:
        return 0


# ── Fandom Lua 스크래핑 ────────────────────────────────────────────────────────

async def fetch_lua_module() -> str | None:
    """Module:Baro/data Lua 소스 다운로드."""
    client = get_client()
    try:
        r = await client.get(
            _FANDOM_API,
            params={
                "action": "query",
                "titles": "Module:Baro/data",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "format": "json",
                "formatversion": "2",
            },
            timeout=30.0,
        )
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", [])
        if pages:
            slots = pages[0].get("revisions", [{}])[0].get("slots", {})
            return slots.get("main", {}).get("content", "")
    except Exception:
        logger.exception("Lua 모듈 다운로드 실패")
    return None


def parse_lua_module(lua_src: str) -> list[BaroItemMeta]:
    """Lua 테이블에서 아이템 파싱."""
    items: list[BaroItemMeta] = []

    # 아이템 블록: ["Item Name"] = { ... }
    # 중첩 중괄호를 고려해 직접 블록 추출
    pattern = re.compile(r'\["([^"]+)"\]\s*=\s*\{', re.DOTALL)
    for m in pattern.finditer(lua_src):
        item_name = m.group(1)
        start = m.end()
        depth, pos = 1, start
        while pos < len(lua_src) and depth > 0:
            if lua_src[pos] == '{':
                depth += 1
            elif lua_src[pos] == '}':
                depth -= 1
            pos += 1
        block = lua_src[start:pos - 1]

        ducat_m  = re.search(r'DucatCost\s*=\s*(\d+)', block)
        credit_m = re.search(r'CreditCost\s*=\s*(\d+)', block)
        type_m   = re.search(r'Type\s*=\s*"([^"]+)"', block)
        pc_m     = re.search(r'PcOfferingDates\s*=\s*\{([^}]+)\}', block, re.DOTALL)

        pc_dates = re.findall(r'"(\d{4}-\d{2}-\d{2})"', pc_m.group(1)) if pc_m else []
        if not pc_dates:
            continue  # PC 날짜 없는 항목 제외

        items.append(BaroItemMeta(
            item_name=item_name,
            ducat_cost=int(ducat_m.group(1)) if ducat_m else 0,
            credit_cost=int(credit_m.group(1)) if credit_m else 0,
            item_type=type_m.group(1) if type_m else "Unknown",
            pc_offering_dates=pc_dates,
        ))

    logger.info("Lua 파싱: %d개 아이템", len(items))
    return items


def save_parsed_items(items: list[BaroItemMeta]) -> dict:
    """파싱 결과를 DB에 upsert."""
    new_items, new_appearances = 0, 0
    all_dates = {d for item in items for d in item.pc_offering_dates}

    with sqlite3.connect(DB_PATH) as conn:
        for date in sorted(all_dates):
            vn = date_to_visit_num(date)
            if vn > 0:
                conn.execute(
                    "INSERT OR IGNORE INTO baro_visits (visit_num, visit_date) VALUES (?,?)",
                    (vn, date),
                )

        for item in items:
            cur = conn.execute(
                "INSERT OR IGNORE INTO baro_items "
                "(item_name, ducat_cost, credit_cost, item_type) VALUES (?,?,?,?)",
                (item.item_name, item.ducat_cost, item.credit_cost, item.item_type),
            )
            if cur.rowcount:
                new_items += 1

            item_id = conn.execute(
                "SELECT id FROM baro_items WHERE item_name=?", (item.item_name,)
            ).fetchone()[0]

            for date in item.pc_offering_dates:
                vn = date_to_visit_num(date)
                if vn > 0:
                    cur2 = conn.execute(
                        "INSERT OR IGNORE INTO baro_appearances (item_id, visit_num) VALUES (?,?)",
                        (item_id, vn),
                    )
                    if cur2.rowcount:
                        new_appearances += 1

    return {"new_items": new_items, "new_appearances": new_appearances}


async def run_scrape() -> dict:
    """전체 스크래핑 파이프라인."""
    lua_src = await fetch_lua_module()
    if not lua_src:
        return {"ok": False, "error": "Lua 모듈 다운로드 실패"}

    items = parse_lua_module(lua_src)
    if not items:
        return {"ok": False, "error": "파싱 결과 없음", "lua_len": len(lua_src)}

    result = save_parsed_items(items)
    return {"ok": True, "parsed": len(items), **result, **get_db_stats()}


# ── 현재 방문 동기화 ───────────────────────────────────────────────────────────

async def sync_current_visit() -> dict:
    """worldstate API → 현재 방문 DB 저장."""
    from src.world.api import get_void_trader
    baro = await get_void_trader()
    if not baro.get("active") or not baro.get("inventory"):
        return {"ok": False, "active": False}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    visit_num = date_to_visit_num(today)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO baro_visits (visit_num, visit_date, location) VALUES (?,?,?)",
            (visit_num, today, baro.get("location", "")),
        )
        for inv in baro["inventory"]:
            conn.execute(
                "INSERT OR IGNORE INTO baro_items "
                "(item_name, ducat_cost, credit_cost, item_type) VALUES (?,?,?,'Current')",
                (inv["item"], inv.get("ducats", 0), inv.get("credits", 0)),
            )
            row = conn.execute(
                "SELECT id FROM baro_items WHERE item_name=?", (inv["item"],)
            ).fetchone()
            if row:
                conn.execute(
                    "INSERT OR IGNORE INTO baro_appearances (item_id, visit_num) VALUES (?,?)",
                    (row[0], visit_num),
                )

    return {"ok": True, "visit_num": visit_num, "items": len(baro["inventory"])}


# ── 피처 매트릭스 (ML 학습용) ──────────────────────────────────────────────────

def _item_visit_nums() -> dict[int, list[int]]:
    """item_id → 방문번호 정렬 리스트."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT item_id, visit_num FROM baro_appearances ORDER BY item_id, visit_num"
        ).fetchall()
    result: dict[int, list[int]] = {}
    for item_id, vn in rows:
        result.setdefault(item_id, []).append(vn)
    return result


def _all_items() -> dict[int, dict]:
    """item_id → {item_name, ducat_cost, item_type}."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, item_name, ducat_cost, item_type FROM baro_items"
        ).fetchall()
    return {r[0]: {"item_name": r[1], "ducat": r[2], "item_type": r[3]} for r in rows}


def build_feature_matrix():
    """(X, y, item_names) 반환 — 시간 순 정렬 보장."""
    with sqlite3.connect(DB_PATH) as conn:
        total_visits = conn.execute(
            "SELECT MAX(visit_num) FROM baro_visits"
        ).fetchone()[0] or 0

    if total_visits < 15:
        return [], [], []

    visit_map  = _item_visit_nums()   # item_id → sorted visit_nums
    items_meta = _all_items()

    # 타입 인코딩 (일관성 유지용)
    all_types  = sorted({m["item_type"] for m in items_meta.values()})
    type_enc   = {t: i for i, t in enumerate(all_types)}

    X: list[list[float]] = []
    y: list[int]         = []
    names: list[str]     = []

    for item_id, visit_nums in visit_map.items():
        if len(visit_nums) < 2:
            continue

        meta     = items_meta[item_id]
        log_ducat = math.log1p(meta["ducat"])
        tenc     = type_enc.get(meta["item_type"], 0)
        vn_set   = set(visit_nums)

        for vi in range(10, total_visits + 1):
            past = [v for v in visit_nums if v < vi]
            if not past:
                continue

            gaps = [past[i+1] - past[i] for i in range(len(past) - 1)] if len(past) > 1 else [14.0]
            avg  = sum(gaps) / len(gaps)
            std  = (sum((g - avg) ** 2 for g in gaps) / len(gaps)) ** 0.5
            vsl  = vi - past[-1]
            ovr  = vsl / avg if avg > 0 else 0.0
            rate = len(past) / vi

            X.append([vsl, avg, std, ovr, len(past), rate, log_ducat, tenc])
            y.append(1 if vi in vn_set else 0)
            names.append(meta["item_name"])

    return X, y, names


def get_item_features_for_prediction() -> list[dict]:
    """예측용 현재 시점 피처 (각 아이템의 최신 상태)."""
    with sqlite3.connect(DB_PATH) as conn:
        total_visits = conn.execute(
            "SELECT MAX(visit_num) FROM baro_visits"
        ).fetchone()[0] or 0

    if total_visits == 0:
        return []

    visit_map  = _item_visit_nums()
    items_meta = _all_items()
    all_types  = sorted({m["item_type"] for m in items_meta.values()})
    type_enc   = {t: i for i, t in enumerate(all_types)}

    result = []
    for item_id, visit_nums in visit_map.items():
        if len(visit_nums) < 2:
            continue

        meta     = items_meta[item_id]
        gaps     = [visit_nums[i+1] - visit_nums[i] for i in range(len(visit_nums) - 1)]
        avg      = sum(gaps) / len(gaps)
        std      = (sum((g - avg) ** 2 for g in gaps) / len(gaps)) ** 0.5
        vsl      = total_visits - visit_nums[-1]
        ovr      = vsl / avg if avg > 0 else 0.0
        rate     = len(visit_nums) / total_visits

        result.append({
            "item_id":          item_id,
            "item_name":        meta["item_name"],
            "ducat_cost":       meta["ducat"],
            "item_type":        meta["item_type"],
            "total_appearances": len(visit_nums),
            "last_visit_num":   visit_nums[-1],
            "visits_since_last": vsl,
            "avg_interval":     round(avg, 1),
            "features": [vsl, avg, std, ovr, len(visit_nums), rate,
                         math.log1p(meta["ducat"]), type_enc.get(meta["item_type"], 0)],
        })

    return result
