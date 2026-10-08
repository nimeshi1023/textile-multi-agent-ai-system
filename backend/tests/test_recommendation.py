"""
Tests for the Phase 4 Recommendation Agent and the IR layer.

Run from the backend folder:  python -m pytest tests/test_recommendation.py -v
Tests that need PostgreSQL, the trained delay model or the built index are skipped
when those are not available.
"""
import ast
import math
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agents import recommendation as rec
from app.agents.recommendation import ACTION_RULES, RecommendationAgent
from app.ir import kb_loader, retriever

BACKEND = Path(__file__).resolve().parents[1]


# ---------- docs must never change ----------
@pytest.fixture(scope="module", autouse=True)
def knowledge_base_unchanged():
    before = kb_loader.docs_fingerprint()
    yield
    assert kb_loader.docs_fingerprint() == before, "knowledge_base/docs/ was modified!"


# ---------- helpers ----------
def mock_db(hist_rate=0.17):
    db = MagicMock()

    def execute(statement, params=None):
        result = MagicMock()
        result.mappings.return_value.fetchone.return_value = None
        result.scalar.return_value = hist_rate
        return result

    db.execute.side_effect = execute
    return db


def make_resource(quantity, days, capacity, workload, stock, usage, lead, reliability, issues):
    available = capacity * (1 - workload)
    required_days = quantity / available
    material_required = quantity * usage
    return {
        "order_id": "TEST-001",
        "resource_status": "INSUFFICIENT" if issues else "SUFFICIENT",
        "issues": issues,
        "machine": {"machine_id": "MCH07", "machine_capacity_per_day": capacity,
                    "machine_current_workload_pct": workload, "status": "Operational"},
        "material": {"material_name": "Dyed Cotton", "stock_qty": stock, "usage_per_unit": usage,
                     "reorder_lead_time_days": 7, "supplier_id": "SUP004"},
        "supplier": {"supplier_id": "SUP004", "avg_lead_time_days": lead, "reliability_score": reliability},
        "calculations": {
            "days_remaining": days, "material_required": material_required,
            "material_available": stock - material_required, "available_capacity_per_day": available,
            "required_production_days": required_days, "capacity_in_deadline": available * days,
            "capacity_shortfall": max(quantity - available * days, 0.0), "tight_deadline": required_days > days,
        },
        "explanation": "test", "explanation_source": "template",
    }


CAPACITY = (make_resource(20000, 10, 1500, 0.3, 40000, 0.5, 5, 0.95,
                          ["MACHINE_CAPACITY_SHORTAGE", "DEADLINE_TOO_TIGHT"]),
            {"product_type": "Denim Jeans", "quantity": 20000, "priority": "High"})
MATERIAL = (make_resource(12000, 10, 2000, 0.4, 3000, 1.2, 16, 0.6,
                          ["MATERIAL_SHORTAGE", "SUPPLIER_DELAY_RISK"]),
            {"product_type": "Cotton T-Shirt", "quantity": 12000, "priority": "Medium"})
SAFE = (make_resource(500, 50, 2000, 0.2, 20000, 0.6, 5, 0.95, []),
        {"product_type": "Cotton T-Shirt", "quantity": 500, "priority": "Low"})

HIGH_RISK = {
    "risk_level": "High", "delay_probability_pct": 87.5, "risk_drivers": ["MACHINE_CAPACITY_SHORTAGE"],
    "top_factors": [{"feature": "capacity_shortfall", "value": True, "direction": "increases risk", "impact": 0.4}],
    "input_features": {"quantity": 20000, "days_remaining": 10},
}


def risk_for(scenario):
    """Real Delay Risk model result for a scenario (needs the trained model)."""
    from app.agents.delay_risk import DelayRiskAgent
    from app.ml.predictor import ModelNotTrainedError
    resource, order = scenario
    try:
        return DelayRiskAgent(mock_db()).run(resource_result=resource, order=order)
    except ModelNotTrainedError:
        pytest.skip("needs model: python -m app.ml.train")


@pytest.fixture
def fresh_retriever(monkeypatch):
    monkeypatch.delenv(retriever.FORCE_BACKEND_ENV, raising=False)
    retriever.reset_retriever()
    yield
    retriever.reset_retriever()


@pytest.fixture
def vector_retriever(fresh_retriever):
    try:
        r = retriever.get_retriever()
    except retriever.IndexNotBuiltError:
        pytest.skip(f"needs index: {retriever.BUILD_COMMAND}")
    if r.name != "chroma+minilm":
        pytest.skip("vector backend not available")
    return r


@pytest.fixture
def tfidf(fresh_retriever, monkeypatch):
    monkeypatch.setenv(retriever.FORCE_BACKEND_ENV, "tfidf")
    return retriever.get_retriever()


@pytest.fixture
def db_session():
    from sqlalchemy import text
    from app.db.session import SessionLocal
    session = SessionLocal()
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        session.close()
        pytest.skip("needs DB")
    yield session
    session.rollback()
    session.close()


# ---------- loader / parser ----------
DOC_TEMPLATE = """Document ID: {id}
Category: Test Category
Title: {title}
Tags: alpha, beta

------------------------------------------------------------
{body}

------------------------------------------------------------
------------------------------------------------------------
"""


def test_real_knowledge_base_has_26_valid_documents():
    docs = kb_loader.load_documents()
    assert sorted(d["document_id"] for d in docs) == [f"KB{n:03d}" for n in range(1, 27)]
    assert all(d["body"] and d["title"] and d["category"] and d["tags"] for d in docs)
    assert not any("---" in d["body"] for d in docs)


def test_parser_reads_several_documents_from_one_file(tmp_path):
    text = DOC_TEMPLATE.format(id="T001", title="First", body="Body one.") + \
           DOC_TEMPLATE.format(id="T002", title="Second", body="Body two.\n\nSecond paragraph.")
    (tmp_path / "multi.txt").write_text(text, encoding="utf-8")
    docs = kb_loader.load_documents(tmp_path)
    assert [d["document_id"] for d in docs] == ["T001", "T002"]
    assert docs[1]["body"] == "Body two.\n\nSecond paragraph."
    assert docs[0]["tags"] == ["alpha", "beta"]
    assert docs[0]["source_file"] == "multi.txt"


def test_parser_reports_missing_field(tmp_path):
    text = DOC_TEMPLATE.format(id="T001", title="", body="Body.")
    (tmp_path / "a.txt").write_text(text, encoding="utf-8")
    with pytest.raises(kb_loader.KnowledgeBaseError, match="T001: missing 'title'"):
        kb_loader.load_documents(tmp_path)


def test_parser_reports_duplicate_id_and_empty_body(tmp_path):
    (tmp_path / "a.txt").write_text(DOC_TEMPLATE.format(id="T001", title="A", body="Body."), encoding="utf-8")
    (tmp_path / "b.txt").write_text(DOC_TEMPLATE.format(id="T001", title="B", body=""), encoding="utf-8")
    with pytest.raises(kb_loader.KnowledgeBaseError) as err:
        kb_loader.load_documents(tmp_path)
    assert "T001: duplicate ID in a.txt and b.txt" in str(err.value)
    assert "empty body" in str(err.value)


def test_long_body_is_split_on_paragraphs():
    doc = {"document_id": "T1", "title": "t", "category": "c", "tags": [], "source_file": "x",
           "body": "\n\n".join(["word " * 200] * 3)}
    chunks = kb_loader.split_long_body(doc)
    assert len(chunks) > 1
    assert all(c["document_id"] == "T1" for c in chunks)
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))


# ---------- retriever ----------
@pytest.mark.parametrize("query, expected", [
    ("machine breakdown", {"KB004", "KB001"}),
    ("raw material shortage", {"KB006"}),
    ("supplier delay", {"KB009", "KB010"}),
    ("fabric defect rework", {"KB013"}),
    ("overtime", {"KB018"}),
    ("outsourcing", {"KB020"}),
    ("machine capacity shortage", {"KB021"}),
])
def test_vector_search_top_document(vector_retriever, query, expected):
    results = retriever.search(query, top_k=3)
    assert results[0]["document_id"] in expected
    assert all(0.0 <= r["score"] <= 1.0 for r in results)
    assert set(results[0]) == {"document_id", "title", "category", "tags", "text", "score", "source_file"}


@pytest.mark.parametrize("backend", ["vector", "tfidf"])
def test_min_score_filter_drops_unrelated_documents(request, backend):
    request.getfixturevalue("vector_retriever" if backend == "vector" else "tfidf")
    for query in ["how to bake bread", "office birthday party catering", "football match results"]:
        assert retriever.search(query, top_k=3) == []


@pytest.mark.parametrize("backend", ["vector", "tfidf"])
def test_category_filter(request, backend):
    request.getfixturevalue("vector_retriever" if backend == "vector" else "tfidf")
    results = retriever.search("supplier delay escalation", top_k=5, category="Supplier Management")
    assert results and all(r["category"] == "Supplier Management" for r in results)


def test_tfidf_fallback_when_vector_backend_fails(fresh_retriever, monkeypatch):
    def broken(self, *args, **kwargs):
        raise OSError("model not cached and no internet")
    monkeypatch.setattr(retriever.ChromaRetriever, "__init__", broken)
    assert retriever.backend_name() == "tfidf"
    assert retriever.search("supplier delay")[0]["document_id"] in {"KB009", "KB010"}


def test_missing_index_is_a_clear_error(fresh_retriever, tmp_path):
    pytest.importorskip("chromadb")
    with pytest.raises(retriever.IndexNotBuiltError, match="python -m app.ir.build_index"):
        retriever.ChromaRetriever(index_dir=tmp_path)


def test_ir_layer_needs_no_llm_or_api_key():
    for path in (BACKEND / "app" / "ir").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any("llm" in m or "groq" in m or "anthropic" in m or "config" in m for m in modules), path.name


# ---------- agent ----------
def test_low_risk_needs_no_action_and_no_retrieval(monkeypatch):
    monkeypatch.setattr(retriever, "search", MagicMock(side_effect=AssertionError("no retrieval for Low")))
    low = {**HIGH_RISK, "risk_level": "Low", "delay_probability_pct": 4.7, "risk_drivers": []}
    out = RecommendationAgent(mock_db()).run("T", risk_result=low, resource_result=SAFE[0])
    assert out["status"] == "no_action_needed"
    assert out["actions"] == []
    assert out["explanation"].startswith("Delay risk is LOW (4.7%)")


def test_high_risk_actions_all_have_real_sources(vector_retriever):
    out = RecommendationAgent(mock_db()).run("T", risk_result=HIGH_RISK, resource_result=CAPACITY[0])
    assert out["status"] == "recommendations_ready"
    kb_ids = {d["document_id"] for d in kb_loader.load_documents()}
    assert 1 <= len(out["actions"]) <= rec.MAX_ACTIONS
    for a in out["actions"]:
        assert a["sources"], a
        assert {s["document_id"] for s in a["sources"]} <= kb_ids      # no invented source IDs
        assert a["requires_manager_approval"] is True
    assert [a["rank"] for a in out["actions"]] == list(range(1, len(out["actions"]) + 1))


def test_action_without_supporting_sop_is_dropped(vector_retriever, monkeypatch):
    fake = {"action": "Teleport the fabric", "query": "teleport fabric instantly",
            "support_terms": ["teleport"]}
    monkeypatch.setitem(ACTION_RULES, "MACHINE_CAPACITY_SHORTAGE",
                        ACTION_RULES["MACHINE_CAPACITY_SHORTAGE"] + [fake])
    out = RecommendationAgent(mock_db()).run("T", risk_result=HIGH_RISK, resource_result=CAPACITY[0])
    assert "Teleport the fabric" not in [a["action"] for a in out["actions"]]
    assert {"action": "Teleport the fabric", "driver": "MACHINE_CAPACITY_SHORTAGE",
            "reason": "no retrieved SOP supports this action"} in out["dropped_actions"]


def test_no_supported_actions_is_reported_honestly(fresh_retriever, monkeypatch):
    monkeypatch.setattr(retriever, "search", lambda *a, **k: [])
    monkeypatch.setattr(retriever, "backend_name", lambda: "test")
    out = RecommendationAgent(mock_db()).run("T", risk_result=HIGH_RISK, resource_result=CAPACITY[0])
    assert out["status"] == "no_supported_actions" and out["actions"] == []
    assert "No action could be backed by a knowledge-base SOP" in out["explanation"]


def test_template_quotes_real_numbers(vector_retriever):
    out = RecommendationAgent(mock_db()).run("T", risk_result=HIGH_RISK, resource_result=CAPACITY[0])
    text = out["explanation"]
    assert text.startswith("Delay risk is HIGH (87.5%).")
    assert "Capacity shortfall of 9,500 units" in text           # 20000 - 1050 x 10
    assert "1,050 units/day available vs 2,000 needed per day" in text
    for a in out["actions"]:
        assert a["sources"][0]["document_id"] in text


def test_works_with_llm_flag_off_and_no_api_key(vector_retriever, monkeypatch):
    import app.services.llm_client as llm

    def no_key(*args, **kwargs):
        raise RuntimeError("Error code: 401 - invalid api key")
    monkeypatch.setattr(llm.LLMClient, "__init__", no_key)

    monkeypatch.delenv("USE_LLM_EXPLANATION", raising=False)
    out = RecommendationAgent(mock_db()).run("T", risk_result=HIGH_RISK, resource_result=CAPACITY[0])
    assert out["explanation_source"] == "template" and out["actions"]

    monkeypatch.setenv("USE_LLM_EXPLANATION", "true")          # flag on, LLM fails -> template
    out = RecommendationAgent(mock_db()).run("T", risk_result=HIGH_RISK, resource_result=CAPACITY[0])
    assert out["explanation_source"] == "template"


def test_agent_does_not_write_to_the_database(vector_retriever):
    db = mock_db()
    RecommendationAgent(db).run("T", risk_result=HIGH_RISK, resource_result=CAPACITY[0])
    db.add.assert_not_called()
    db.commit.assert_not_called()


# ---------- scenarios with the real stack (real model + real retrieval) ----------
def test_scenario_capacity_shortage(vector_retriever):
    out = RecommendationAgent(mock_db()).run("T", risk_result=risk_for(CAPACITY), resource_result=CAPACITY[0])
    print(f"\nCAPACITY: {out['risk_level']} {out['delay_probability_pct']}% -> "
          + "; ".join(f"{a['action']} {[s['document_id'] for s in a['sources']]}" for a in out["actions"]))
    assert out["status"] == "recommendations_ready"
    sources = {s["document_id"] for a in out["actions"] for s in a["sources"]}
    assert {"KB020", "KB018"} <= sources                          # outsourcing + overtime SOPs
    assert sources & {"KB017", "KB021", "KB022"}                  # capacity / reallocation SOPs


def test_scenario_material_shortage(vector_retriever):
    out = RecommendationAgent(mock_db()).run("T", risk_result=risk_for(MATERIAL), resource_result=MATERIAL[0])
    print(f"\nMATERIAL: {out['risk_level']} {out['delay_probability_pct']}% -> "
          + "; ".join(f"{a['action']} {[s['document_id'] for s in a['sources']]}" for a in out["actions"]))
    assert out["status"] == "recommendations_ready"
    actions = [a["action"] for a in out["actions"]]
    assert "Activate an alternate supplier for the material" in actions
    assert "Raise an emergency purchase for the missing material" in actions


def test_scenario_low_risk(vector_retriever):
    out = RecommendationAgent(mock_db()).run("T", risk_result=risk_for(SAFE), resource_result=SAFE[0])
    print(f"\nSAFE: {out['risk_level']} {out['delay_probability_pct']}% -> {out['status']}")
    assert out["status"] == "no_action_needed"


def test_scenarios_also_work_with_tfidf_fallback(tfidf):
    out = RecommendationAgent(mock_db()).run("T", risk_result=HIGH_RISK, resource_result=CAPACITY[0])
    assert out["retrieval_backend"] == "tfidf"
    assert out["actions"] and all(a["sources"] for a in out["actions"])


# ---------- API ----------
@pytest.fixture
def client(override_auth):   # run as a signed-in test manager (see conftest.py)
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_api_search_and_kb(client, vector_retriever):
    body = client.post("/recommendation/search", json={"query": "supplier delay", "top_k": 2}).json()
    assert body["results"][0]["document_id"] in {"KB009", "KB010"} and len(body["results"]) <= 2
    kb = client.get("/recommendation/kb").json()
    assert kb["document_count"] == 26 and kb["index_status"] == "built"


def test_api_bad_input_is_422(client):
    assert client.post("/recommendation/search", json={"query": "  "}).status_code == 422
    assert client.post("/recommendation/generate", json={}).status_code == 422
    assert client.post("/recommendation/decision", json={
        "order_id": "X", "action": "a", "decision": "overridden", "decided_by": "m"}).status_code == 422
    assert client.post("/recommendation/decision", json={
        "order_id": "X", "action": "a", "decision": "maybe", "decided_by": "m"}).status_code == 422


def test_api_index_not_built_is_503(client, fresh_retriever, monkeypatch, tmp_path):
    pytest.importorskip("chromadb")
    monkeypatch.setattr(retriever, "INDEX_DIR", tmp_path)
    original = retriever.ChromaRetriever.__init__
    monkeypatch.setattr(retriever.ChromaRetriever, "__init__",
                        lambda self, index_dir=None: original(self, index_dir=tmp_path))
    response = client.post("/recommendation/search", json={"query": "overtime"})
    assert response.status_code == 503
    assert retriever.BUILD_COMMAND in response.json()["detail"]


def test_api_generate_with_results_passed_in(client, vector_retriever):
    response = client.post("/recommendation/generate", json={
        "order_id": "TEST-001", "risk_result": HIGH_RISK, "resource_result": CAPACITY[0]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "recommendations_ready"


def test_api_unknown_order_is_404(client, db_session, vector_retriever):
    assert client.post("/recommendation/generate", json={"order_id": "NOPE-404"}).status_code == 404
    assert client.get("/recommendation/decisions/NOPE-404").status_code == 404
    assert client.post("/recommendation/decision", json={
        "order_id": "NOPE-404", "action": "a", "decision": "approved", "decided_by": "m"}).status_code == 404


def test_api_decision_saves_and_reads_back(client, db_session):
    from sqlalchemy import text
    order_id = db_session.execute(text("SELECT cus_ord_id FROM cust_ord_table ORDER BY cus_ord_id LIMIT 1")).scalar()
    db_session.rollback()
    if order_id is None:
        pytest.skip("no orders in cust_ord_table")
    payload = {"order_id": order_id, "action": "PYTEST action - safe to delete",
               "decision": "rejected", "comment": "pytest", "decided_by": "pytest"}
    saved = client.post("/recommendation/decision", json=payload)
    assert saved.status_code == 200, saved.text
    row_id = saved.json()["id"]
    try:
        history = client.get(f"/recommendation/decisions/{order_id}").json()
        assert any(h["id"] == row_id and h["decision"] == "rejected" and h["decided_by"] == "pytest"
                   for h in history)
    finally:
        db_session.execute(text("DELETE FROM recommendation_decisions WHERE id = :id AND decided_by = 'pytest'"),
                           {"id": row_id})
        db_session.commit()
