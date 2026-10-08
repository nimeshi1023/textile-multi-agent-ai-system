"""
Tests for the read-only Manager Dashboard routes.

Run from the backend folder:  python -m pytest tests/test_dashboard.py -v
"""
from unittest.mock import MagicMock

import pytest

from app.api.routes import dashboard

SUMMARY_KEYS = {
    "total_orders", "high_priority_orders", "orders_due_within_7_days", "orders_by_priority",
    "orders_by_product_type", "orders_by_material", "orders_per_day", "deadlines_next_14_days",
    "historical_delay_rate_by_product", "top_delay_reasons", "decisions_by_type", "decisions_total",
    "generated_at",
}
LIST_KEYS = SUMMARY_KEYS - {"total_orders", "high_priority_orders", "orders_due_within_7_days",
                            "decisions_total", "generated_at"}


@pytest.fixture(autouse=True)
def empty_risk_cache():
    dashboard._risk_cache.update(at=0.0, data=None)
    yield
    dashboard._risk_cache.update(at=0.0, data=None)


@pytest.fixture
def anonymous_client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture
def client(override_auth):   # signed-in test manager (see conftest.py)
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture
def needs_db():
    from sqlalchemy import text
    from app.db.session import SessionLocal
    session = SessionLocal()
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("needs DB")
    finally:
        session.close()


@pytest.fixture
def needs_model():
    from app.ml import predictor
    try:
        predictor.load_model()
    except predictor.ModelNotTrainedError:
        pytest.skip("needs model: python -m app.ml.train")


def empty_session():
    """A database session where every table is empty."""
    db = MagicMock()

    def execute(statement, params=None):
        result = MagicMock()
        result.mappings.return_value.fetchone.return_value = None
        result.mappings.return_value.fetchall.return_value = []
        result.scalar.return_value = True if "to_regclass" in str(statement) else None
        return result

    db.execute.side_effect = execute
    return db


def use_session(session):
    from app.db.session import get_db
    from app.main import app

    def override():
        yield session
    app.dependency_overrides[get_db] = override
    return lambda: app.dependency_overrides.pop(get_db, None)


def test_routes_need_a_token(anonymous_client):
    assert anonymous_client.get("/dashboard/summary").status_code == 401
    assert anonymous_client.get("/dashboard/risk-overview").status_code == 401


def test_summary_shape_with_real_data(client, needs_db):
    response = client.get("/dashboard/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == SUMMARY_KEYS
    for key in LIST_KEYS:
        assert isinstance(body[key], list), key
    for key in ("orders_by_priority", "orders_by_product_type", "orders_by_material", "top_delay_reasons"):
        assert all(set(row) == {"label", "count"} for row in body[key]), key
    assert all(0.0 <= row["rate"] <= 1.0 for row in body["historical_delay_rate_by_product"])
    assert "No major risk factor detected" not in [r["label"] for r in body["top_delay_reasons"]]
    assert body["total_orders"] >= sum(r["count"] for r in body["orders_by_priority"]) - 0
    assert body["decisions_total"] == sum(r["count"] for r in body["decisions_by_type"])


def test_summary_with_empty_database_gives_zeros_and_empty_lists(client):
    restore = use_session(empty_session())
    try:
        body = client.get("/dashboard/summary").json()
    finally:
        restore()
    assert body["total_orders"] == body["high_priority_orders"] == body["orders_due_within_7_days"] == 0
    assert body["decisions_total"] == 0
    assert all(body[key] == [] for key in LIST_KEYS)


def test_risk_overview_with_empty_database(client, needs_model):
    restore = use_session(empty_session())
    try:
        body = client.get("/dashboard/risk-overview").json()
    finally:
        restore()
    assert body["orders"] == []
    assert body["counts"] == {"Low": 0, "Medium": 0, "High": 0, "Unavailable": 0}


def test_risk_overview_shape_no_writes_no_llm_and_cache(client, needs_db, needs_model, monkeypatch):
    import app.services.llm_client as llm
    from app.agents.delay_risk import DelayRiskAgent
    from app.db.session import SessionLocal

    def forbidden(*args, **kwargs):
        raise AssertionError("must not be called")
    monkeypatch.setattr(llm.LLMClient, "generate", forbidden)
    monkeypatch.setattr(DelayRiskAgent, "explain", forbidden)

    session = SessionLocal()
    writes = []
    for method in ("commit", "add", "flush", "delete"):
        monkeypatch.setattr(session, method, lambda *a, _m=method, **k: writes.append(_m))
    restore = use_session(session)
    try:
        first = client.get("/dashboard/risk-overview", params={"refresh": "true"})
        second = client.get("/dashboard/risk-overview")
    finally:
        restore()
        session.rollback()
        session.close()

    assert first.status_code == 200, first.text
    body = first.json()
    assert writes == []                                   # nothing was written
    assert body["cached"] is False and second.json()["cached"] is True
    assert set(body["counts"]) == {"Low", "Medium", "High", "Unavailable"}
    assert sum(body["counts"].values()) == len(body["orders"]) <= dashboard.RISK_OVERVIEW_ORDERS
    for order in body["orders"]:
        assert order["risk_level"] in body["counts"]
        if order["risk_level"] != "Unavailable":
            assert 0.0 <= order["delay_probability_pct"] <= 100.0


def test_one_failing_order_does_not_break_the_overview(client, needs_db, needs_model, monkeypatch):
    from app.agents.delay_risk import DelayRiskAgent

    original = DelayRiskAgent.get_resource_result
    calls = {"n": 0}

    def flaky(self, order_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated Resource Agent failure")
        return original(self, order_id)
    monkeypatch.setattr(DelayRiskAgent, "get_resource_result", flaky)

    body = client.get("/dashboard/risk-overview", params={"refresh": "true"}).json()
    if not body["orders"]:
        pytest.skip("no orders in cust_ord_table")
    assert body["orders"][0]["risk_level"] == "Unavailable"
    assert "simulated Resource Agent failure" in body["orders"][0]["error"]
