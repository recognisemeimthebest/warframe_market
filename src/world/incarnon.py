"""인카논 제네시스 어댑터 주간 로테이션 계산.

데이터 소스:
- 현재 주차: worldState EndlessXpSchedule (EXC_HARD) — 항상 정확
- 미래 주차: 하드코딩된 로테이션 + 에포크 기반 계산

로테이션 업데이트 방법:
  INCARNON_ROTATION 리스트에 주차(5개 무기 배열) 추가/수정.
  현재 주차와 매칭되면 자동으로 인덱스 재계산됨.
"""

from __future__ import annotations
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── 전체 로테이션 (커뮤니티 기록 기반, 순서 수정 가능) ──────────────────────
# 각 리스트 = 1주차 어댑터 5종
# 마지막 검증: 2026-04-13 기준 (Zylok/Sibear/Dread/Despair/Hate 확인됨)
INCARNON_ROTATION: list[list[str]] = [
    # ── 시리즈 1 (Duviri 출시, 2023-04) ──────────────────────────────────
    ["Lato", "Braton", "Skana", "Paris", "Kunai"],
    ["Boar", "Gammacor", "Angstrum", "Gorgon", "Anku"],
    ["Bo", "Latron", "Furis", "Furax", "Strun"],
    ["Lex", "Magistar", "Bolto", "Attica", "Ceramic Dagger"],
    ["Bronco", "Torid", "Dual Toxocyst", "Dual Ichors", "Miter"],
    ["Atomos", "Ack & Brunt", "Soma", "Staticor", "Twin Gremlins"],
    # ── 시리즈 2 ──────────────────────────────────────────────────────────
    ["Burston", "Cronus", "Flux Rifle", "Fusilai", "Cestra"],
    ["Fang", "Granmu Prism", "Hikou", "Knell", "Sicarus"],
    ["Zylok", "Sibear", "Dread", "Despair", "Hate"],   # ← 2026-04-13 확인됨
]

# ── 에포크 ─────────────────────────────────────────────────────────────────
# 2026-04-13 00:00 UTC = 인덱스 8 (Zylok 주차) 시작
# 실제 worldState EndlessXpSchedule.Activation 값으로 확인됨
# 주간 리셋: 매주 월요일 00:00 UTC
_EPOCH_UNIX = 1776038400   # 2026-04-13 00:00 UTC (worldState 확인)
_EPOCH_ROTATION_IDX = 8    # 위 날짜의 로테이션 인덱스
_WEEK_SECS = 7 * 24 * 3600


def _current_week_idx() -> int:
    """현재 주차의 로테이션 인덱스 (에포크 기반)."""
    elapsed_weeks = int((time.time() - _EPOCH_UNIX) // _WEEK_SECS)
    n = len(INCARNON_ROTATION)
    return (_EPOCH_ROTATION_IDX + elapsed_weeks) % n


def _week_start(offset_weeks: int = 0) -> datetime:
    """offset_weeks 후의 주차 시작 시각 (UTC)."""
    elapsed_weeks = int((time.time() - _EPOCH_UNIX) // _WEEK_SECS)
    target_week_start = _EPOCH_UNIX + (elapsed_weeks + offset_weeks) * _WEEK_SECS
    return datetime.fromtimestamp(target_week_start, tz=timezone.utc)


def get_rotation_schedule(weeks: int = 9) -> list[dict]:
    """현재 주차부터 weeks개 주차의 인카논 로테이션 반환.

    Returns list of:
        {
            "week_offset": 0,           # 0=이번주, 1=다음주, ...
            "start_date": "04/13",      # MM/DD
            "weapons": [...],           # 5종 무기
            "rotation_idx": 8,          # 전체 로테이션에서의 인덱스
        }
    """
    n = len(INCARNON_ROTATION)
    cur_idx = _current_week_idx()
    result = []
    for i in range(weeks):
        idx = (cur_idx + i) % n
        start = _week_start(i)
        result.append({
            "week_offset": i,
            "start_date": start.strftime("%m/%d"),
            "weapons": INCARNON_ROTATION[idx],
            "rotation_idx": idx,
        })
    return result


def find_weapon(query: str) -> dict | None:
    """특정 무기가 몇 주 후에 오는지 반환.

    Returns:
        {
            "weapon": "Lato",
            "week_offset": 3,       # 몇 주 후 (0=이번주)
            "start_date": "05/04",
            "all_weapons": [...],   # 같이 오는 다른 4종
        }
        None if not found.
    """
    q = query.strip().lower()
    n = len(INCARNON_ROTATION)
    cur_idx = _current_week_idx()

    for i in range(n):
        idx = (cur_idx + i) % n
        for w in INCARNON_ROTATION[idx]:
            if q in w.lower() or w.lower() in q:
                start = _week_start(i)
                return {
                    "weapon": w,
                    "week_offset": i,
                    "start_date": start.strftime("%m/%d"),
                    "all_weapons": INCARNON_ROTATION[idx],
                    "rotation_idx": idx,
                }
    return None
