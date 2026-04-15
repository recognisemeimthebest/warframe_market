"""프라임 단종(Vaulted) 여부 판단 모듈.

단종 = 해당 프라임 파츠를 얻을 수 있는 렐릭이 현재 드롭 풀에 없는 상태.
현역 = 현재 렐릭에서 파밍 가능.
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────
# 현재 단종된 프라임 기반명 목록 (소문자, 언더스코어)
# 예: "ash" → ash_prime_set, ash_prime_neuroptics_blueprint 등 모두 단종 처리
# 업데이트 기준: 2026-04 기준
# ──────────────────────────────────────────────────────
VAULTED_BASES: frozenset[str] = frozenset({
    # 워프레임 프라임
    "ash",
    "atlas",
    "banshee",
    "chroma",
    "ember",
    "equinox",
    "frost",
    "hydroid",
    "ivara",
    "limbo",
    "loki",
    "mag",
    "mesa",
    "mirage",
    "nekros",
    "nezha",
    "nidus",
    "nova",
    "nyx",
    "oberon",
    "octavia",
    "rhino",
    "saryn",
    "trinity",
    "valkyr",
    "vauban",
    "volt",
    "wukong",
    "zephyr",
    # 주무기 프라임 (대표 단종 목록)
    "boltor",
    "braton",
    "burston",
    "cernos",
    "dex_sybaris",
    "latron",
    "opticor",
    "paris",
    "rubico",
    "snipetron",
    "soma",
    "supra",
    "tiberon",
    "tigris",
    "vectis",
    # 보조무기 프라임
    "akbolto",
    "akbronco",
    "aksomati",
    "ballistica",
    "bronco",
    "despair",
    "furis",
    "lex",
    "magnus",
    "pyrana",
    "sicarus",
    "twin_gremlins",
    "vasto",
    # 근접무기 프라임
    "ankyros",
    "bo",
    "dakra",
    "dual_cleavers",
    "dual_kamas",
    "fragor",
    "fang",
    "galatine",
    "gram",
    "hate",
    "nikana",
    "orthos",
    "pangolin",
    "reaper",
    "scindo",
    "skana",
    "silva_and_aegis",
    "venka",
    "zaw",
})


def is_vaulted(slug: str) -> bool | None:
    """slug의 단종 여부를 반환한다.

    Returns:
        True  — 단종된 프라임
        False — 현역 프라임 (현재 파밍 가능)
        None  — 프라임 아이템이 아님
    """
    if "_prime" not in slug:
        return None

    # 기반명 추출: "rhino_prime_set" → "rhino", "ash_prime_neuroptics" → "ash"
    base = slug.split("_prime")[0]

    if base in VAULTED_BASES:
        return True

    return False


def is_vaulted_by_name(name: str) -> bool | None:
    """영문 표시 이름으로 단종 여부를 반환한다.

    예: "Ash Prime Neuroptics Blueprint" → True

    Returns:
        True  — 단종된 프라임
        False — 현역 프라임
        None  — 프라임 아이템이 아님
    """
    lower = name.lower()
    if "prime" not in lower:
        return None

    # "ash prime ..." → "ash"
    idx = lower.find(" prime")
    if idx == -1:
        return None

    base = lower[:idx].strip().replace(" ", "_")
    if base in VAULTED_BASES:
        return True

    return False
