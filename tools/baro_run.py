"""바로 키티어 파이프라인 실행 스크립트.

사용법:
  python tools/baro_run.py scrape        # 위키에서 데이터 수집
  python tools/baro_run.py train         # 모델 학습 (200 trials, 4 workers)
  python tools/baro_run.py train --fast  # 빠른 테스트 (20 trials)
  python tools/baro_run.py predict       # 예측 결과 출력
  python tools/baro_run.py all           # scrape → train → predict 한번에
  python tools/baro_run.py stats         # DB 현황만 출력
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market.baro import init_baro_db, run_scrape, get_db_stats
from src.market.baro_model import train_model, predict_next_visit, get_model_info


def _bar(prob_pct: float, width: int = 20) -> str:
    filled = round(prob_pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def cmd_stats():
    init_baro_db()
    s = get_db_stats()
    print("\n── DB 현황 ─────────────────────────")
    print(f"  총 방문:       {s['total_visits']:>6}회")
    print(f"  고유 아이템:   {s['total_items']:>6}개")
    print(f"  등장 기록:     {s['total_appearances']:>6}건")
    print(f"  마지막 방문:   #{s['last_visit_num']}  ({s['last_visit_date']})")

    m = get_model_info()
    print("\n── 모델 현황 ────────────────────────")
    if m.get("trained"):
        print(f"  AUC:           {m['best_auc']:.4f}")
        print(f"  학습일:        {m['trained_at'][:10]}")
        imp = m.get("feature_importance", {})
        if imp:
            label_map = {
                "visits_since_last": "미등장 횟수",
                "avg_interval":      "평균 간격",
                "std_interval":      "간격 편차",
                "overdue_ratio":     "오버듀 비율",
                "appearances_so_far":"총 등장 수",
                "appearance_rate":   "등장률",
                "log_ducat":         "덕키 (log)",
                "item_type_enc":     "아이템 타입",
            }
            sorted_imp = sorted(imp.items(), key=lambda x: x[1], reverse=True)
            max_v = sorted_imp[0][1] if sorted_imp else 1
            print("\n  피처 중요도:")
            for k, v in sorted_imp:
                b = _bar(v / max_v * 100, 15)
                print(f"    {label_map.get(k, k):<14} {b}  {v:.0f}")
    else:
        print("  학습된 모델 없음")
    print()


async def cmd_scrape():
    print("\n📡 위키 Lua 모듈 스크래핑 시작...")
    init_baro_db()
    result = await run_scrape()
    if result["ok"]:
        print(f"  ✅ 파싱 완료: {result['parsed']}개 아이템")
        print(f"  신규 아이템: {result['new_items']}개")
        print(f"  신규 등장 기록: {result['new_appearances']}건")
        print(f"  DB 총 방문: {result['total_visits']}회")
    else:
        print(f"  ❌ 실패: {result.get('error')}")
    print()


def cmd_train(fast: bool = False):
    trials  = 20  if fast else 200
    workers = 2   if fast else 4
    label   = "빠른 테스트" if fast else "전체 학습"

    print(f"\n🤖 LightGBM + Optuna {label} (trials={trials}, workers={workers})")
    print("  (Pi 5에서 전체 학습 ~10-20분 소요)")
    print()

    result = train_model(n_trials=trials, n_jobs=workers)
    if result["ok"]:
        print(f"\n  ✅ 학습 완료!")
        print(f"  AUC:            {result['best_auc']:.4f}")
        print(f"  Train samples:  {result['train_samples']:,}")
        print(f"  Val samples:    {result['val_samples']:,}")
        print(f"  Best params:")
        for k, v in result["best_params"].items():
            print(f"    {k}: {v}")
        print()
        if result.get("importance"):
            print("  피처 중요도 (gain):")
            sorted_imp = sorted(result["importance"].items(), key=lambda x: x[1], reverse=True)
            max_v = sorted_imp[0][1] if sorted_imp else 1
            label_map = {
                "visits_since_last": "미등장 횟수",
                "avg_interval":      "평균 간격",
                "std_interval":      "간격 편차",
                "overdue_ratio":     "오버듀 비율",
                "appearances_so_far":"총 등장 수",
                "appearance_rate":   "등장률",
                "log_ducat":         "덕키 (log)",
                "item_type_enc":     "아이템 타입",
            }
            for k, v in sorted_imp:
                b = _bar(v / max_v * 100, 20)
                print(f"    {label_map.get(k, k):<14} {b}  {v:.0f}")
    else:
        print(f"  ❌ 실패: {result.get('error')}")
    print()


def cmd_predict(top: int = 30):
    print(f"\n🔮 다음 바로 방문 예측 (상위 {top}개)")
    m = get_model_info()
    if not m.get("trained"):
        print("  ⚠️  학습된 모델 없음. `python tools/baro_run.py train` 먼저 실행하세요.")
        return

    s = get_db_stats()
    print(f"  (총 {s['total_visits']}회 방문 데이터, 모델 AUC={m['best_auc']:.4f})\n")

    preds = predict_next_visit(top_n=top)
    if not preds:
        print("  예측 결과 없음.")
        return

    header = f"{'#':>3}  {'아이템':<36} {'확률':>6}  {'확률 바':20}  {'미등장':>5}  {'평균간격':>7}  {'타입':<14}  덕키"
    print(header)
    print("-" * len(header))

    for i, p in enumerate(preds, 1):
        bar   = _bar(p["probability_pct"], 20)
        pct   = f"{p['probability_pct']:>5.1f}%"
        name  = p["item_name"][:35].ljust(36)
        vsl   = f"{p['visits_since_last']:>4}회"
        avg   = f"{p['avg_interval']:>6.1f}회"
        itype = p["item_type"][:13].ljust(14)
        ducat = p["ducat_cost"]

        # 확률 높을수록 강조
        prefix = "🔴" if p["probability_pct"] >= 70 else ("🟡" if p["probability_pct"] >= 40 else "⚪")
        print(f"{i:>3}  {name} {pct}  {bar}  {vsl}  {avg}  {itype}  {ducat}")
    print()


async def main():
    parser = argparse.ArgumentParser(description="바로 키티어 파이프라인")
    parser.add_argument("cmd", choices=["scrape", "train", "predict", "stats", "all"])
    parser.add_argument("--fast", action="store_true", help="빠른 테스트 (20 trials)")
    parser.add_argument("--top",  type=int, default=30, help="예측 결과 상위 N개")
    args = parser.parse_args()

    if args.cmd == "stats":
        cmd_stats()
    elif args.cmd == "scrape":
        await cmd_scrape()
        cmd_stats()
    elif args.cmd == "train":
        cmd_stats()
        cmd_train(fast=args.fast)
    elif args.cmd == "predict":
        cmd_predict(top=args.top)
    elif args.cmd == "all":
        await cmd_scrape()
        cmd_train(fast=args.fast)
        cmd_predict(top=args.top)


if __name__ == "__main__":
    asyncio.run(main())
