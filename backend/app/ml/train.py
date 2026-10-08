"""
Train the Delay Risk model.

Run from the backend folder:
    cd backend
    python -m app.ml.train

Why ONE model, and why a Random Forest (RandomForestClassifier)?
  - The data is tabular with mixed numeric and categorical features.
  - Trees capture non-linear interactions (e.g. high workload only matters
    when the deadline is short) without us writing them by hand.
  - No feature scaling is needed (quantities and fractions can be used as-is).
  - Averaging many trees makes it robust on a small dataset (3000 rows here)
    and less prone to overfitting than a single decision tree.
  - It gives built-in feature importance, which helps explain the predictions.
The delay probability is predict_proba(): the share of trees voting "delayed".

The model is trained ONLY by running this script - never on API start.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from app.ml.features import (
    BOOLEAN_FEATURES,
    CATEGORICAL_FEATURES,
    DERIVED_FEATURES,
    FEATURES,
    NUMERIC_FEATURES,
    TARGET,
    load_training_data,
)


# ---- Hyperparameters (simple, fixed; no model search) ----
MODEL_NAME = "RandomForestClassifier"
N_ESTIMATORS = 300          # number of trees
MIN_SAMPLES_LEAF = 3        # every leaf needs >= 3 orders -> less overfitting
MAX_FEATURES = "sqrt"       # features tried per split (standard for classification)
CLASS_WEIGHT = "balanced"   # 59% on time / 41% delayed -> weight classes equally
RANDOM_STATE = 42           # reproducible results

CV_FOLDS = 5
TEST_SIZE = 0.20

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_FILE = "delay_model.joblib"
METRICS_FILE = "metrics.json"


def build_pipeline() -> Pipeline:
    preprocess = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("num", "passthrough", NUMERIC_FEATURES + BOOLEAN_FEATURES + DERIVED_FEATURES),
        ]
    )
    model = RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        min_samples_leaf=MIN_SAMPLES_LEAF,
        max_features=MAX_FEATURES,
        class_weight=CLASS_WEIGHT,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    return Pipeline([("preprocess", preprocess), ("model", model)])


def hyperparameters() -> dict:
    return {
        "n_estimators": N_ESTIMATORS,
        "min_samples_leaf": MIN_SAMPLES_LEAF,
        "max_features": MAX_FEATURES,
        "class_weight": CLASS_WEIGHT,
        "random_state": RANDOM_STATE,
    }


def classification_metrics(y_true, proba) -> dict:
    pred = (proba >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "accuracy": round(accuracy_score(y_true, pred), 4),
        "precision": round(precision_score(y_true, pred, zero_division=0), 4),
        "recall": round(recall_score(y_true, pred, zero_division=0), 4),
        "f1": round(f1_score(y_true, pred, zero_division=0), 4),
        "roc_auc": round(roc_auc_score(y_true, proba), 4),
        "brier": round(brier_score_loss(y_true, proba), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def group_metrics(df_test: pd.DataFrame, y_true, proba, column: str) -> dict:
    """Bias check: does the model behave similarly for every group?"""
    result = {}
    pred = (proba >= 0.5).astype(int)
    for group in sorted(df_test[column].unique()):
        mask = (df_test[column] == group).to_numpy()
        y_g, p_g = y_true[mask], pred[mask]
        result[group] = {
            "n": int(mask.sum()),
            "actual_delay_rate": round(float(y_g.mean()), 4),
            "mean_predicted_probability": round(float(proba[mask].mean()), 4),
            "accuracy": round(accuracy_score(y_g, p_g), 4),
            "recall": round(recall_score(y_g, p_g, zero_division=0), 4) if y_g.sum() else None,
            "precision": round(precision_score(y_g, p_g, zero_division=0), 4) if p_g.sum() else None,
        }
    return result


def grouped_importances(pipeline: Pipeline) -> dict:
    """Random Forest importances, one-hot columns summed back to the original feature."""
    names = pipeline.named_steps["preprocess"].get_feature_names_out()
    importances = pipeline.named_steps["model"].feature_importances_
    grouped = {}
    for name, value in zip(names, importances):
        prefix, column = name.split("__", 1)
        if prefix == "cat":
            column = next(c for c in CATEGORICAL_FEATURES if column.startswith(c + "_"))
        grouped[column] = grouped.get(column, 0.0) + float(value)
    return {k: round(v, 4) for k, v in sorted(grouped.items(), key=lambda kv: -kv[1])}


def train(engine=None, artifacts_dir: Path = ARTIFACTS_DIR, verbose: bool = True) -> dict:
    if engine is None:
        from app.db.session import engine as default_engine
        engine = default_engine

    df = load_training_data(engine)
    X, y = df[FEATURES], df[TARGET].astype(int).to_numpy()

    # 1) Stratified 5-fold cross-validation of the single model
    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    cv_raw = cross_validate(
        build_pipeline(), X, y, cv=cv, scoring=["roc_auc", "f1", "precision", "recall"]
    )
    cv_scores = {
        metric: {
            "mean": round(float(np.mean(cv_raw[f"test_{metric}"])), 4),
            "std": round(float(np.std(cv_raw[f"test_{metric}"])), 4),
        }
        for metric in ["roc_auc", "f1", "precision", "recall"]
    }

    # 2) Held-out 20% stratified test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE
    )
    raw = build_pipeline().fit(X_train, y_train)
    raw_proba = raw.predict_proba(X_test)[:, 1]
    raw_metrics = classification_metrics(y_test, raw_proba)

    # 3) Calibration: wrap the SAME Random Forest pipeline in CalibratedClassifierCV
    #    (sigmoid). Random Forest probabilities are often too cautious near 0 and 1.
    #    We keep calibration ONLY if it lowers the Brier score on the held-out split,
    #    because then the probabilities match real delay frequencies better.
    calibrated = CalibratedClassifierCV(build_pipeline(), method="sigmoid", cv=CV_FOLDS)
    calibrated.fit(X_train, y_train)
    cal_proba = calibrated.predict_proba(X_test)[:, 1]
    cal_metrics = classification_metrics(y_test, cal_proba)
    use_calibration = cal_metrics["brier"] < raw_metrics["brier"]

    test_metrics = cal_metrics if use_calibration else raw_metrics
    test_proba = cal_proba if use_calibration else raw_proba
    bias_check = {
        "product_type": group_metrics(X_test, y_test, test_proba, "product_type"),
        "priority": group_metrics(X_test, y_test, test_proba, "priority"),
    }

    # 4) Refit on ALL rows for the saved model
    full_raw = build_pipeline().fit(X, y)
    if use_calibration:
        final_model = CalibratedClassifierCV(build_pipeline(), method="sigmoid", cv=CV_FOLDS)
        final_model.fit(X, y)
    else:
        final_model = full_raw

    trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Baselines for local explanations: median for numbers, most common value otherwise
    baselines = {col: float(X[col].median()) for col in NUMERIC_FEATURES + DERIVED_FEATURES}
    baselines.update({col: X[col].mode().iloc[0].item() for col in BOOLEAN_FEATURES})
    baselines.update({col: str(X[col].mode().iloc[0]) for col in CATEGORICAL_FEATURES})

    metrics = {
        "model_name": MODEL_NAME,
        "trained_at": trained_at,
        "data_source": "postgresql: orders",
        "row_count": int(len(df)),
        "class_balance": {"on_time": int((y == 0).sum()), "delayed": int((y == 1).sum())},
        "features": FEATURES,
        "hyperparameters": hyperparameters(),
        "cross_validation": {"folds": CV_FOLDS, **cv_scores},
        "test_split": {"test_size": TEST_SIZE, "n_test": int(len(y_test)), **test_metrics},
        "calibration": {
            "method": "sigmoid",
            "used": bool(use_calibration),
            "brier_uncalibrated": raw_metrics["brier"],
            "brier_calibrated": cal_metrics["brier"],
            "reason": (
                "Calibration lowered the held-out Brier score, so calibrated probabilities are used."
                if use_calibration
                else "Calibration did not lower the held-out Brier score, so the raw Random Forest is used."
            ),
        },
        "feature_importances": grouped_importances(full_raw),
        "bias_check": bias_check,
    }

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": final_model,
        "model_name": MODEL_NAME,
        "features": FEATURES,
        "baselines": baselines,
        "trained_at": trained_at,
        "calibrated": bool(use_calibration),
        "roc_auc": test_metrics["roc_auc"],
    }
    joblib.dump(bundle, artifacts_dir / MODEL_FILE)
    (artifacts_dir / METRICS_FILE).write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    if verbose:
        print_report(metrics, artifacts_dir)
    return metrics


def print_report(metrics: dict, artifacts_dir: Path) -> None:
    print(f"\nModel: {metrics['model_name']}   rows: {metrics['row_count']}   "
          f"class balance: {metrics['class_balance']}")
    print(f"\nStratified {metrics['cross_validation']['folds']}-fold cross-validation")
    for m in ["roc_auc", "f1", "precision", "recall"]:
        s = metrics["cross_validation"][m]
        print(f"  {m:<10} {s['mean']:.4f} ± {s['std']:.4f}")
    t = metrics["test_split"]
    print(f"\nHeld-out test split ({t['n_test']} rows)")
    for m in ["accuracy", "precision", "recall", "f1", "roc_auc", "brier"]:
        print(f"  {m:<10} {t[m]:.4f}")
    print(f"  confusion  {t['confusion_matrix']}")
    c = metrics["calibration"]
    print(f"\nCalibration: Brier raw {c['brier_uncalibrated']:.4f} vs calibrated "
          f"{c['brier_calibrated']:.4f} -> used: {c['used']}")
    print("\nTop feature importances")
    for name, value in list(metrics["feature_importances"].items())[:8]:
        print(f"  {name:<32} {value:.4f}")
    print("\nSaved files")
    for f in sorted(artifacts_dir.iterdir()):
        print(f"  {f}  ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    train()
