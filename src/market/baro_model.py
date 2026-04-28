"""바로 키티어 ML 모델 — LightGBM + Optuna (DART dropout + early stopping)."""

import asyncio
import logging
import pickle
from pathlib import Path

from src.config import DATA_DIR
from src.market.baro import (
    FEATURE_NAMES,
    build_feature_matrix,
    get_item_features_for_prediction,
    get_db_stats,
)

logger = logging.getLogger(__name__)

MODEL_PATH = DATA_DIR / "baro_model.pkl"


# ── 학습 ──────────────────────────────────────────────────────────────────────

def train_model(n_trials: int = 200, n_jobs: int = 4) -> dict:
    """Optuna 하이퍼파라미터 탐색 → LightGBM 최종 학습."""
    try:
        import lightgbm as lgb
        import numpy as np
        import optuna
    except ImportError as e:
        return {"ok": False, "error": f"의존성 없음: {e}"}

    X_list, y_list, _ = build_feature_matrix()
    if not X_list:
        return {"ok": False, "error": "학습 데이터 없음 (DB 스크래핑 먼저 실행)"}

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list,  dtype=np.int32)

    # 시간 순 split — 마지막 15%를 validation
    split = int(len(X) * 0.85)
    X_tr, y_tr = X[:split], y[:split]
    X_va, y_va = X[split:], y[split:]

    pos_count = int(y_tr.sum())
    neg_count = len(y_tr) - pos_count
    pos_weight = neg_count / max(pos_count, 1)
    logger.info("바로 모델 학습: train=%d pos=%d(%.1f%%) val=%d pos_weight=%.1f",
                len(X_tr), pos_count, 100 * pos_count / len(y_tr),
                len(X_va), pos_weight)

    # ── Optuna objective ──
    # Dataset은 thread-safe하지 않으므로 각 trial 안에서 생성
    def objective(trial: "optuna.Trial") -> float:
        boosting = trial.suggest_categorical("boosting_type", ["gbdt", "dart"])
        params: dict = {
            "objective":          "binary",
            "metric":             "auc",
            "boosting_type":      boosting,
            "num_leaves":         trial.suggest_int("num_leaves", 20, 200),
            "max_depth":          trial.suggest_int("max_depth", 3, 12),
            "learning_rate":      trial.suggest_float("learning_rate", 5e-3, 0.3, log=True),
            "min_child_samples":  trial.suggest_int("min_child_samples", 5, 100),
            "feature_fraction":   trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction":   trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq":       trial.suggest_int("bagging_freq", 1, 10),
            "reg_alpha":          trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda":         trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "scale_pos_weight":   pos_weight,
            "feature_pre_filter": False,  # DART min_child_samples 동적 변경 지원
            "verbosity":          -1,
            "n_jobs":             1,
        }
        if boosting == "dart":
            params["drop_rate"] = trial.suggest_float("drop_rate", 0.05, 0.4)
            params["skip_drop"] = trial.suggest_float("skip_drop", 0.3,  0.7)
            params["max_drop"]  = trial.suggest_int("max_drop",    1,    50)

        # 각 trial마다 독립 Dataset (병렬 n_jobs 안전)
        t_data = lgb.Dataset(X_tr, label=y_tr, feature_name=FEATURE_NAMES, free_raw_data=False)
        v_data = lgb.Dataset(X_va, label=y_va, feature_name=FEATURE_NAMES,
                             reference=t_data, free_raw_data=False)
        try:
            mdl = lgb.train(
                params, t_data,
                num_boost_round=600,
                valid_sets=[v_data],
                callbacks=[
                    lgb.early_stopping(stopping_rounds=40, verbose=False),
                    lgb.log_evaluation(period=-1),
                ],
            )
            return mdl.best_score["valid_0"]["auc"]
        except Exception:
            return 0.0

    # ── Optuna 탐색 ──
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.TPESampler(seed=42)
    study   = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, n_jobs=n_jobs, show_progress_bar=False)

    best_params = study.best_params
    best_auc    = study.best_value
    logger.info("Optuna 완료: AUC=%.4f  params=%s", best_auc, best_params)

    # ── 최종 모델 (best params, 더 많은 라운드) ──
    d_tr = lgb.Dataset(X_tr, label=y_tr, feature_name=FEATURE_NAMES, free_raw_data=False)
    d_va = lgb.Dataset(X_va, label=y_va, feature_name=FEATURE_NAMES,
                       reference=d_tr, free_raw_data=False)

    final_params = {
        "objective":          "binary",
        "metric":             "auc",
        "scale_pos_weight":   pos_weight,
        "feature_pre_filter": False,
        "verbosity":          -1,
        "n_jobs":             n_jobs,
        **best_params,
    }
    final_model = lgb.train(
        final_params, d_tr,
        num_boost_round=1500,
        valid_sets=[d_va],
        callbacks=[
            lgb.early_stopping(stopping_rounds=60, verbose=False),
            lgb.log_evaluation(period=200),
        ],
    )

    # feature importance
    importance = dict(zip(
        FEATURE_NAMES,
        final_model.feature_importance(importance_type="gain").tolist(),
    ))

    bundle = {
        "model":         final_model,
        "best_params":   best_params,
        "best_auc":      best_auc,
        "feature_names": FEATURE_NAMES,
        "feature_importance": importance,
        "pos_weight":    pos_weight,
        "train_samples": len(X_tr),
        "val_samples":   len(X_va),
        "trained_at":    __import__("datetime").datetime.now().isoformat(),
    }
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(bundle, f)

    logger.info("바로 모델 저장 완료: %s", MODEL_PATH)
    return {
        "ok":           True,
        "best_auc":     round(best_auc, 4),
        "best_params":  best_params,
        "importance":   importance,
        "train_samples": len(X_tr),
        "val_samples":  len(X_va),
        "model_path":   str(MODEL_PATH),
    }


# ── 예측 ──────────────────────────────────────────────────────────────────────

def predict_next_visit(top_n: int = 30) -> list[dict]:
    """다음 방문 등장 확률 예측 (모델 없으면 빈 리스트)."""
    if not MODEL_PATH.exists():
        return []

    try:
        import numpy as np
        import lightgbm as lgb
    except ImportError:
        return []

    with open(MODEL_PATH, "rb") as f:
        bundle: dict = pickle.load(f)
    model: lgb.Booster = bundle["model"]

    item_feats = get_item_features_for_prediction()
    if not item_feats:
        return []

    X = np.array([d["features"] for d in item_feats], dtype=np.float32)
    probs = model.predict(X).tolist()

    results = []
    for feat, prob in zip(item_feats, probs):
        results.append({
            "item_name":         feat["item_name"],
            "probability":       round(prob, 4),
            "probability_pct":   round(prob * 100, 1),
            "ducat_cost":        feat["ducat_cost"],
            "item_type":         feat["item_type"],
            "total_appearances": feat["total_appearances"],
            "last_visit_num":    feat["last_visit_num"],
            "visits_since_last": feat["visits_since_last"],
            "avg_interval":      feat["avg_interval"],
        })

    results.sort(key=lambda x: x["probability"], reverse=True)
    return results[:top_n]


def get_model_info() -> dict:
    if not MODEL_PATH.exists():
        return {"trained": False}
    try:
        with open(MODEL_PATH, "rb") as f:
            b = pickle.load(f)
        return {
            "trained":    True,
            "best_auc":   b.get("best_auc"),
            "trained_at": b.get("trained_at"),
            "best_params": b.get("best_params"),
            "feature_importance": b.get("feature_importance"),
        }
    except Exception:
        return {"trained": False, "error": "모델 파일 손상"}
