"""리벤 모드 입력 필드용 정형 데이터.

게시글 작성 시 드롭다운/체크박스에 노출되는 옵션들.
warframe.market의 riven 속성 슬러그를 그대로 사용한다.
"""

POLARITIES = ["마두라이", "내러멀", "바자린", "유나이로", "자마티", "페나가"]


def polarity_options() -> list[dict]:
    return [{"value": p, "label": p} for p in POLARITIES]


# (slug, 한글, 분류)
RIVEN_STATS: list[tuple[str, str, str]] = [
    ("base_damage_/_melee_damage", "기본 데미지", "공격력"),
    ("damage_vs_corpus", "코퍼스 데미지", "공격력"),
    ("damage_vs_grineer", "그리니어 데미지", "공격력"),
    ("damage_vs_infested", "인페스티드 데미지", "공격력"),
    ("multishot", "다중사격", "공격력"),
    ("critical_chance", "치명타 확률", "치명타"),
    ("critical_chance_for_slide_attack", "슬라이드 치명타 확률", "치명타"),
    ("critical_damage", "치명타 피해", "치명타"),
    ("status_chance", "상태이상 확률", "상태"),
    ("status_duration", "상태이상 지속시간", "상태"),
    ("cold_damage", "냉기 데미지", "원소"),
    ("electric_damage", "전기 데미지", "원소"),
    ("fire_damage", "화염 데미지", "원소"),
    ("toxin_damage", "독성 데미지", "원소"),
    ("impact_damage", "충격 피해", "물리"),
    ("puncture_damage", "관통 피해", "물리"),
    ("slash_damage", "베기 피해", "물리"),
    ("fire_rate_/_attack_speed", "발사 속도/공격 속도", "속도"),
    ("reload_speed", "재장전 속도", "속도"),
    ("magazine_capacity", "탄창 용량", "탄약"),
    ("ammo_maximum", "최대 탄약", "탄약"),
    ("projectile_speed", "발사체 속도", "기타"),
    ("punch_through", "관통", "기타"),
    ("zoom", "줌", "기타"),
    ("recoil", "반동", "기타"),
    ("range", "사거리", "근접"),
    ("finisher_damage", "피니셔 데미지", "근접"),
    ("combo_duration", "콤보 지속시간", "근접"),
    ("chance_to_gain_combo_count", "콤보 카운터 획득 확률", "근접"),
    ("chance_to_gain_extra_combo_count", "추가 콤보 카운터 획득 확률", "근접"),
    ("heat_damage", "열 데미지", "원소"),
]


def stat_options() -> list[dict]:
    return [
        {"value": slug, "label": ko, "group": group}
        for slug, ko, group in RIVEN_STATS
    ]
