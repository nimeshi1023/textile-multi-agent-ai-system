"""
Load the trained Delay Risk model once, predict, and explain single predictions.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import pandas as pd

from app.ml.features import BOOLEAN_FEATURES, CATEGORICAL_FEATURES, FEATURES
from app.ml.train import ARTIFACTS_DIR, METRICS_FILE, MODEL_FILE


TRAIN_COMMAND = "cd backend && python -m app.ml.train"
MODEL_PATH = ARTIFACTS_DIR / MODEL_FILE
METRICS_PATH = ARTIFACTS_DIR / METRICS_FILE

# Loaded model bundles, keyed by file path (loaded once per process)
_model_cache: Dict[str, Dict[str, Any]] = {}


class ModelNotTrainedError(RuntimeError):
    def __init__(self):
        super().__init__(f"Model not trained. Run: {TRAIN_COMMAND}")


def load_model(path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(path or MODEL_PATH)
    key = str(path)
    if key not in _model_cache:
        if not path.exists():
            raise ModelNotTrainedError()
        _model_cache[key] = joblib.load(path)
    return _model_cache[key]


def clear_model_cache() -> None:
    _model_cache.clear()


def load_metrics(path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(path or METRICS_PATH)
    if not path.exists():
        raise ModelNotTrainedError()
    return json.loads(path.read_text(encoding="utf-8"))


def predict_proba(bundle: Dict[str, Any], frame: pd.DataFrame) -> float:
    """Probability of 'delayed' (share of trees voting delayed) for a one-row frame."""
    return float(bundle["model"].predict_proba(frame[FEATURES])[0, 1])


def explain_local(bundle: Dict[str, Any], frame: pd.DataFrame, top_n: int = 5) -> List[Dict[str, Any]]:
    """
    Top factors for THIS prediction: feature, value, direction and relative impact.

    Uses SHAP TreeExplainer when the `shap` package is installed (and the model is
    a plain Random Forest pipeline); otherwise local perturbation.
    """
    contributions = None
    try:
        contributions = _shap_contributions(bundle, frame)
    except ImportError:
        pass
    if contributions is None:
        contributions = _perturbation_contributions(bundle, frame)

    total = sum(abs(v) for v in contributions.values()) or 1.0
    ranked = sorted(contributions.items(), key=lambda kv: -abs(kv[1]))[:top_n]

    factors = []
    for feature, delta in ranked:
        value = frame[feature].iloc[0]
        if feature in BOOLEAN_FEATURES:
            value = bool(value)
        elif feature in CATEGORICAL_FEATURES:
            value = str(value)
        else:
            value = round(float(value), 4)
        factors.append({
            "feature": feature,
            "value": value,
            "direction": "increases risk" if delta > 0 else "reduces risk",
            "impact": round(abs(delta) / total, 4),
        })
    return factors


def _perturbation_contributions(bundle: Dict[str, Any], frame: pd.DataFrame) -> Dict[str, float]:
    """
    Replace one feature at a time with its typical training value (median for
    numbers, most common value otherwise) and measure how the probability changes.
    Positive = this order's actual value pushes the risk UP.
    Categorical features are perturbed before one-hot encoding, so each one is
    already reported under its original name.
    """
    base = predict_proba(bundle, frame)
    contributions = {}
    for feature in FEATURES:
        typical = bundle["baselines"][feature]
        if frame[feature].iloc[0] == typical:
            contributions[feature] = 0.0
            continue
        changed = frame.copy()
        changed[feature] = typical
        contributions[feature] = base - predict_proba(bundle, changed)
    return contributions


def _shap_contributions(bundle: Dict[str, Any], frame: pd.DataFrame) -> Optional[Dict[str, float]]:
    import shap  # optional dependency; ImportError -> perturbation fallback

    model = bundle["model"]
    if not hasattr(model, "named_steps"):
        return None  # calibrated wrapper: use perturbation instead
    preprocess, forest = model.named_steps["preprocess"], model.named_steps["model"]
    encoded = preprocess.transform(frame[FEATURES])
    if hasattr(encoded, "toarray"):
        encoded = encoded.toarray()
    values = shap.TreeExplainer(forest).shap_values(encoded)
    # Older SHAP: list [class0, class1]; newer: array (rows, features, classes)
    row = values[1][0] if isinstance(values, list) else values[0, :, 1]

    # Sum one-hot columns back to their original feature name
    contributions: Dict[str, float] = {}
    for name, value in zip(preprocess.get_feature_names_out(), row):
        prefix, column = name.split("__", 1)
        if prefix == "cat":
            column = next(c for c in CATEGORICAL_FEATURES if column.startswith(c + "_"))
        contributions[column] = contributions.get(column, 0.0) + float(value)
    return contributions
