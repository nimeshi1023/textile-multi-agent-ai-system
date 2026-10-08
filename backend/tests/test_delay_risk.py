"""
Tests for the Phase 3 Delay Prediction / Risk Agent.

Run from the backend folder:  python -m pytest tests/test_delay_risk.py -v
Tests marked "needs DB" / "needs model" are skipped when PostgreSQL or the
trained model file is not available.
"""
import ast
import math
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sklearn.ensemble import RandomForestClassifier

from app.agents.delay_risk import (
    LOW_MAX,
    MEDIUM_MAX,
    DelayRiskAgent,
    InvalidRiskInputError,
)
from app.ml import predictor
from app.ml.features import (
    BASE_FEATURES,
    FEATURES,
    LEAKAGE_COLUMNS,
    REQUIRED_DAYS_CAP,
    features_from_resource_result,
)
from app.ml.train import build_pipeline


# ---------- helpers ----------
def make_resource(
    quantity=1000, days_remaining=30, capacity=1500.0, workload=0.2,
    stock=20000.0, usage=0.5, lead=5, reliability=0.95, status="Operational",
    issues=None,
):
    """A Resource Agent result shaped exactly like ResourceAnalyzeResponse."""
    available = capacity * (1 - (workload / 100 if workload > 1 else workload))
    required_days = quantity / available if available > 0 else math.inf
    in_deadline = available * max(days_remaining, 0)
    material_required = quantity * usage
    return {
        "order_id": "TEST-001",
        "resource_status": "INSUFFICIENT" if issues else "SUFFICIENT",
        "issues": issues or [],
        "machine": {"machine_id": "MCH01", "machine_capacity_per_day": capacity,
                    "machine_current_workload_pct": workload, "status": status},
        "material": {"material_name": "Dyed Cotton", "stock_qty": stock, "usage_per_unit": usage,
                     "reorder_lead_time_days": 7, "supplier_id": "SUP001"},
        "supplier": {"supplier_id": "SUP001", "avg_lead_time_days": lead,
                     "reliability_score": reliability},
        "calculations": {
            "days_remaining": days_remaining,
            "material_required": material_required,
            "material_available": stock - material_required,
            "available_capacity_per_day": available,
            "required_production_days": required_days,
            "capacity_in_deadline": in_deadline,
            "capacity_shortfall": max(quantity - in_deadline, 0.0),
            "tight_deadline": required_days > max(days_remaining, 0),
        },
        "explanation": "test",
        "explanation_source": "template",
        "data_source": "postgresql",
    }


SAFE = dict(quantity=500, days_remaining=50, capacity=2000.0, workload=0.2,
            stock=20000.0, usage=0.6, lead=5, reliability=0.95)
SAFE_ORDER = {"product_type": "Cotton T-Shirt", "quantity": 500, "priority": "Low"}

RISKY = dict(quantity=20000, days_remaining=7, capacity=1200.0, workload=0.9,
             stock=5000.0, usage=1.2, lead=16, reliability=0.6,
             issues=["MATERIAL_SHORTAGE", "MACHINE_CAPACITY_SHORTAGE",
                     "DEADLINE_TOO_TIGHT", "SUPPLIER_DELAY_RISK"])
RISKY_ORDER = {"product_type": "Denim Jeans", "quantity": 20000, "priority": "High"}


def mock_db(hist_rate=0.17):
    """A fake session: no order rows, a fixed historical rate, and recorded calls."""
    db = MagicMock()

    def execute(statement, params=None):
        result = MagicMock()
        result.mappings.return_value.fetchone.return_value = None
        result.scalar.return_value = hist_rate
        return result

    db.execute.side_effect = execute
    return db


@pytest.fixture
def bundle():
    try:
        return predictor.load_model()
    except predictor.ModelNotTrainedError:
        pytest.skip("needs model: run python -m app.ml.train")


@pytest.fixture
def db_session():
    from app.db.session import SessionLocal
    session = SessionLocal()
    try:
        from sqlalchemy import text
        session.execute(text("SELECT 1"))
    except Exception:
        session.close()
        pytest.skip("needs DB")
    yield session
    session.rollback()
    session.close()


# ---------- feature builder ----------
def test_workload_fraction_is_kept():
    f, _ = features_from_resource_result(make_resource(workload=0.53), SAFE_ORDER, 0.17)
    assert f["machine_current_workload_pct"] == pytest.approx(0.53)


def test_workload_percent_is_converted_to_fraction():
    f, _ = features_from_resource_result(make_resource(workload=53), SAFE_ORDER, 0.17)
    assert f["machine_current_workload_pct"] == pytest.approx(0.53)


def test_resource_fields_map_to_training_units():
    r = make_resource(quantity=20000, days_remaining=10, capacity=1500.0, workload=0.0,
                      stock=3000.0, usage=0.25, lead=16, reliability=0.6)
    f, missing = features_from_resource_result(r, RISKY_ORDER, 0.2)
    assert missing == []
    assert f["capacity_shortfall"] is True               # 5000 units -> boolean
    assert f["material_stock_available"] == 3000.0       # stock_qty, not stock minus required
    assert f["material_shortage"] is True                # 5000 required > 3000 stock
    assert f["supplier_risk"] is True                    # reliability < 0.8 and lead > 12
    assert f["production_to_deadline_ratio"] == pytest.approx((20000 / 1500) / 10)


def test_no_capacity_infinite_days_is_capped():
    f, _ = features_from_resource_result(make_resource(workload=1.0), SAFE_ORDER, 0.17)
    assert f["required_production_days"] == REQUIRED_DAYS_CAP


# ---------- leakage ----------
def test_no_leakage_columns_in_features():
    assert not set(LEAKAGE_COLUMNS) & set(FEATURES)
    assert not set(LEAKAGE_COLUMNS) & set(BASE_FEATURES)


def test_saved_model_uses_the_same_leak_free_features(bundle):
    assert bundle["features"] == FEATURES


# ---------- thresholds ----------
@pytest.mark.parametrize("probability, expected", [
    (0.0, "Low"), (0.30, "Low"), (0.31, "Medium"),
    (0.60, "Medium"), (0.61, "High"), (1.0, "High"),
])
def test_risk_level_boundaries(probability, expected):
    assert LOW_MAX == 0.30 and MEDIUM_MAX == 0.60
    assert DelayRiskAgent.classify_risk(probability) == expected


# ---------- missing / unknown values ----------
def test_unknown_product_and_priority_do_not_crash(bundle):
    agent = DelayRiskAgent(mock_db())
    result = agent.run(resource_result=make_resource(**SAFE),
                       order={"product_type": "Space Suit", "quantity": 500, "priority": "Super-Urgent"})
    assert 0.0 <= result["delay_probability"] <= 1.0


def test_missing_order_facts_get_safe_defaults_and_are_listed(bundle):
    agent = DelayRiskAgent(mock_db())
    result = agent.run(resource_result=make_resource(**SAFE))   # no order facts at all
    assert set(result["missing_features"]) == {"quantity", "product_type", "priority"}
    assert result["input_features"]["quantity"] == 500          # derived from capacity x days
    assert result["input_features"]["priority"] == "Medium"


def test_too_many_missing_features_is_an_error(bundle):
    resource = make_resource(**SAFE)
    resource.update(machine=None, material=None, supplier=None, calculations=None,
                    issues=["MATERIAL_NOT_FOUND"])
    with pytest.raises(InvalidRiskInputError, match="Too many missing features"):
        DelayRiskAgent(mock_db()).run(resource_result=resource, order=SAFE_ORDER)


# ---------- model missing ----------
def test_model_missing_gives_clear_error(tmp_path):
    missing = tmp_path / "no_model.joblib"
    with pytest.raises(predictor.ModelNotTrainedError) as err:
        predictor.load_model(missing)
    assert str(err.value) == f"Model not trained. Run: {predictor.TRAIN_COMMAND}"
    with pytest.raises(predictor.ModelNotTrainedError):
        DelayRiskAgent(mock_db(), model_path=missing).run(resource_result=make_resource())


# ---------- probability + explanation ----------
@pytest.mark.parametrize("scenario", [SAFE, RISKY, dict(quantity=8000, days_remaining=20, workload=0.6)])
def test_probability_is_between_0_and_1(bundle, scenario):
    result = DelayRiskAgent(mock_db()).run(resource_result=make_resource(**scenario), order=SAFE_ORDER)
    assert 0.0 <= result["delay_probability"] <= 1.0
    assert result["delay_probability_pct"] == pytest.approx(result["delay_probability"] * 100, abs=0.05)


def test_template_contains_the_real_numbers(bundle):
    result = DelayRiskAgent(mock_db()).run(resource_result=make_resource(**RISKY), order=RISKY_ORDER)
    text = result["explanation"]
    feats = result["input_features"]
    assert result["explanation_source"] == "template"
    assert text.startswith(f"Delay risk is {result['risk_level'].upper()} ({result['delay_probability_pct']:.1f}%)")
    assert f"{feats['required_production_days']:.1f} production days" in text
    assert f"{feats['days_remaining']:.0f} days remaining" in text
    assert "90%" in text                                 # workload 0.9 shown as a percent
    assert len(result["top_factors"]) == 5


def test_llm_flag_off_by_default_and_errors_fall_back(bundle, monkeypatch):
    monkeypatch.delenv("USE_LLM_EXPLANATION", raising=False)
    agent = DelayRiskAgent(mock_db())
    assert agent.run(resource_result=make_resource(**SAFE), order=SAFE_ORDER)["explanation_source"] == "template"

    monkeypatch.setenv("USE_LLM_EXPLANATION", "true")
    def broken(*args, **kwargs):
        raise RuntimeError("Error code: 429 - rate limit")
    monkeypatch.setattr(DelayRiskAgent, "_llm_polish", broken)
    result = agent.run(resource_result=make_resource(**SAFE), order=SAFE_ORDER)
    assert result["explanation_source"] == "template"


# ---------- read-only ----------
def test_agent_never_writes_to_the_database(bundle):
    db = mock_db()
    DelayRiskAgent(db).run(resource_result=make_resource(**RISKY), order=RISKY_ORDER)
    db.add.assert_not_called()
    db.commit.assert_not_called()
    db.flush.assert_not_called()
    db.delete.assert_not_called()
    sql = [str(c.args[0]).strip().split()[0].upper() for c in db.execute.call_args_list]
    assert set(sql) <= {"SET", "SELECT"}
    assert any("READ ONLY" in str(c.args[0]) for c in db.execute.call_args_list)


def test_read_only_transaction_rejects_writes(db_session):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    DelayRiskAgent(db_session)._read_only()
    with pytest.raises(DBAPIError, match="read-only transaction"):
        db_session.execute(text("CREATE TEMP TABLE should_fail (x int)"))


# ---------- exactly one model type ----------
def test_pipeline_uses_only_random_forest():
    pipeline = build_pipeline()
    assert type(pipeline.named_steps["model"]) is RandomForestClassifier


def test_train_script_imports_no_other_algorithm():
    source = (Path(__file__).resolve().parents[1] / "app" / "ml" / "train.py").read_text(encoding="utf-8")
    imported = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("sklearn")
        for alias in node.names
    }
    estimators = {"RandomForestClassifier", "LogisticRegression", "GradientBoostingClassifier",
                  "HistGradientBoostingClassifier", "SVC", "KNeighborsClassifier",
                  "DecisionTreeClassifier", "MLPClassifier", "GaussianNB", "XGBClassifier",
                  "GridSearchCV", "RandomizedSearchCV"}
    assert imported & estimators == {"RandomForestClassifier"}


def test_saved_model_is_a_random_forest(bundle):
    model = bundle["model"]
    pipelines = [c.estimator for c in model.calibrated_classifiers_] if bundle["calibrated"] else [model]
    assert all(type(p.named_steps["model"]) is RandomForestClassifier for p in pipelines)
    assert bundle["model_name"] == "RandomForestClassifier"


# ---------- scenarios with the real model ----------
def test_scenario_safe_order_is_low(bundle):
    result = DelayRiskAgent(mock_db()).run(resource_result=make_resource(**SAFE), order=SAFE_ORDER)
    print(f"\nSAFE scenario: {result['delay_probability_pct']}% -> {result['risk_level']}")
    assert result["risk_level"] == "Low"


def test_scenario_risky_order_is_high(bundle):
    result = DelayRiskAgent(mock_db()).run(resource_result=make_resource(**RISKY), order=RISKY_ORDER)
    print(f"\nRISKY scenario: {result['delay_probability_pct']}% -> {result['risk_level']}")
    assert result["risk_level"] == "High"
    assert result["risk_drivers"] == RISKY["issues"]


# ---------- API ----------
@pytest.fixture
def client(override_auth):   # run as a signed-in test manager (see conftest.py)
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_api_health(client, bundle):
    body = client.get("/risk/health").json()
    assert body["model_loaded"] is True


def test_api_model_info(client, bundle):
    response = client.get("/risk/model-info")
    assert response.status_code == 200
    assert response.json()["model_name"] == "RandomForestClassifier"


def test_api_predict_with_resource_result(client, bundle):
    response = client.post("/risk/predict", json={"resource_result": make_resource(**RISKY),
                                                  "order": RISKY_ORDER})
    assert response.status_code == 200, response.text
    assert response.json()["risk_level"] in {"Low", "Medium", "High"}


def test_api_predict_with_order_id(client, bundle, db_session):
    from sqlalchemy import text
    latest = db_session.execute(text(
        "SELECT o.cus_ord_id FROM cust_ord_table o JOIN materials m "
        "ON LOWER(TRIM(m.material_name)) = LOWER(TRIM(o.material_name)) "
        "ORDER BY o.cus_ord_id DESC LIMIT 1")).scalar()
    if latest is None:
        pytest.skip("no order with a known material in cust_ord_table")
    response = client.post("/risk/predict", json={"order_id": latest})
    assert response.status_code == 200, response.text
    assert response.json()["order_id"] == latest


def test_api_unknown_order_is_404(client, bundle, db_session):
    response = client.post("/risk/predict", json={"order_id": "DOES-NOT-EXIST"})
    assert response.status_code == 404


def test_api_bad_input_is_422(client):
    assert client.post("/risk/predict", json={}).status_code == 422


def test_api_model_not_trained_is_503(client, tmp_path, monkeypatch):
    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "missing.joblib")
    monkeypatch.setattr(predictor, "METRICS_PATH", tmp_path / "missing.json")
    response = client.post("/risk/predict", json={"resource_result": make_resource()})
    assert response.status_code == 503
    assert predictor.TRAIN_COMMAND in response.json()["detail"]
    assert client.get("/risk/model-info").status_code == 503
    assert client.get("/risk/health").json()["model_loaded"] is False
