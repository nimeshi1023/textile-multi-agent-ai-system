"""
Tests for manager authentication (sign up, sign in, lockout, tokens, protected API).

Run from the backend folder:  python -m pytest tests/test_auth.py -v
Uses the real PostgreSQL database; every test manager has a PYTEST_ prefix and is deleted afterwards.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
from sqlalchemy import text

from app.core import security

PASSWORD = "Textile2026"


@pytest.fixture
def db():
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


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app
    yield TestClient(app)
    db.execute(text("DELETE FROM managers WHERE manager_id LIKE 'PYTEST%' OR email LIKE '%@pytest.example.com'"))
    db.commit()


def signup_payload(manager_id="pytest_mgr1", email="Mgr1@PyTest.example.com", **overrides):
    payload = {"manager_type": "Production Manager", "manager_id": manager_id, "email": email,
               "password": PASSWORD, "confirm_password": PASSWORD}
    payload.update(overrides)
    return payload


def signed_up(client, **kwargs):
    response = client.post("/auth/signup", json=signup_payload(**kwargs))
    assert response.status_code == 201, response.text
    return response.json()


def login(client, manager_id="pytest_mgr1", password=PASSWORD):
    return client.post("/auth/login", json={"manager_id": manager_id, "password": password})


def token_for(client, **kwargs):
    signed_up(client, **kwargs)
    response = login(client, kwargs.get("manager_id", "pytest_mgr1"))
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def error_fields(response):
    return {err["loc"][-1] for err in response.json()["detail"]}


@pytest.fixture
def clock(monkeypatch):
    """Controllable clock for lockout tests."""
    state = {"now": datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(security, "utcnow", lambda: state["now"])
    return state


# ---------- sign up ----------
def test_signup_success_normalises_id_and_email(client):
    profile = signed_up(client)
    assert profile["manager_id"] == "PYTEST_MGR1"
    assert profile["email"] == "mgr1@pytest.example.com"
    assert profile["manager_type"] == "Production Manager"
    assert "password" not in str(profile).lower()


def test_duplicate_manager_id_is_409_case_insensitive(client):
    signed_up(client)
    response = client.post("/auth/signup", json=signup_payload(manager_id="PyTest_MGR1", email="other@pytest.example.com"))
    assert response.status_code == 409
    assert response.json()["detail"] == {"field": "manager_id", "message": "Manager ID already exists"}


def test_duplicate_email_is_409_case_insensitive(client):
    signed_up(client)
    response = client.post("/auth/signup", json=signup_payload(manager_id="pytest_mgr2", email="MGR1@pytest.EXAMPLE.com"))
    assert response.status_code == 409
    assert response.json()["detail"]["field"] == "email"


@pytest.mark.parametrize("overrides, field", [
    ({"email": "not-an-email"}, "email"),
    ({"password": "short1A", "confirm_password": "short1A"}, "password"),        # < 8 chars
    ({"password": "alllower123", "confirm_password": "alllower123"}, "password"),  # no uppercase
    ({"password": "ALLUPPER123", "confirm_password": "ALLUPPER123"}, "password"),  # no lowercase
    ({"password": "NoDigitsHere", "confirm_password": "NoDigitsHere"}, "password"),
    ({"confirm_password": "Different2026"}, "confirm_password"),
    ({"manager_type": "CEO"}, "manager_type"),
    ({"manager_id": "ab"}, "manager_id"),                                          # too short
    ({"manager_id": "bad id!"}, "manager_id"),                                     # bad characters
])
def test_signup_validation_errors_are_field_level_422(client, overrides, field):
    response = client.post("/auth/signup", json=signup_payload(**overrides))
    assert response.status_code == 422
    assert field in error_fields(response)


def test_password_is_stored_as_bcrypt_hash_and_never_returned(client, db):
    profile = signed_up(client)
    stored = db.execute(text("SELECT password_hash FROM managers WHERE manager_id = 'PYTEST_MGR1'")).scalar()
    assert stored.startswith("$2b$12$") and PASSWORD not in stored
    assert bcrypt.checkpw(PASSWORD.encode(), stored.encode())
    login_body = login(client).text
    me_body = client.get("/auth/me", headers=bearer(login(client).json()["access_token"])).text
    for body in (str(profile), login_body, me_body):
        assert "password_hash" not in body and stored not in body and PASSWORD not in body


# ---------- sign in ----------
def test_login_success_returns_token_and_profile(client):
    signed_up(client)
    response = login(client, manager_id="pytest_MGR1")   # ID is case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == security.auth_settings.AUTH_TOKEN_EXPIRE_MINUTES * 60
    assert body["manager"]["manager_id"] == "PYTEST_MGR1"
    claims = security.decode_access_token(body["access_token"])
    assert claims["sub"] == "PYTEST_MGR1" and claims["manager_type"] == "Production Manager"


def test_wrong_password_and_unknown_id_give_the_same_generic_error(client):
    signed_up(client)
    wrong = login(client, password="Wrong2026x")
    unknown = login(client, manager_id="PYTEST_NOBODY")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid Manager ID or password"}


def test_unknown_id_still_runs_a_bcrypt_check(client, monkeypatch):
    calls = []
    original = security.verify_password
    monkeypatch.setattr(security, "verify_password", lambda p, h: calls.append(h) or original(p, h))
    login(client, manager_id="PYTEST_NOBODY")
    assert calls == [security.DUMMY_HASH]


def test_lockout_after_5_failures_and_unlock_after_15_minutes(client, db, clock):
    signed_up(client)
    for _ in range(4):
        assert login(client, password="Wrong2026x").status_code == 401
    fifth = login(client, password="Wrong2026x")
    assert fifth.status_code == 429
    assert "Try again in 15 minute(s)" in fifth.json()["detail"]
    assert fifth.headers["Retry-After"] == str(15 * 60)

    clock["now"] += timedelta(minutes=10)
    locked = login(client)                                   # correct password, still locked
    assert locked.status_code == 429 and "5 minute(s)" in locked.json()["detail"]

    clock["now"] += timedelta(minutes=6)                    # 16 minutes after the lock
    assert login(client).status_code == 200
    row = db.execute(text("SELECT failed_login_attempts, locked_until FROM managers "
                          "WHERE manager_id = 'PYTEST_MGR1'")).fetchone()
    assert tuple(row) == (0, None)


def test_successful_login_resets_the_failure_counter(client, clock):
    signed_up(client)
    for _ in range(4):
        login(client, password="Wrong2026x")
    assert login(client).status_code == 200
    for _ in range(4):                                       # 4 more failures: still not locked
        assert login(client, password="Wrong2026x").status_code == 401


# ---------- tokens ----------
def test_me_with_valid_token(client):
    token = token_for(client)
    response = client.get("/auth/me", headers=bearer(token))
    assert response.status_code == 200
    assert response.json()["manager_id"] == "PYTEST_MGR1"
    assert response.json()["last_login_at"] is not None


def test_expired_token_is_401(client):
    signed_up(client)
    expired = security.create_access_token("PYTEST_MGR1", "Production Manager", expires_delta=timedelta(seconds=-5))
    response = client.get("/auth/me", headers=bearer(expired))
    assert response.status_code == 401
    assert response.json()["detail"] == "Session expired, please sign in again"


def test_tampered_or_foreign_token_is_401(client):
    import jwt
    token = token_for(client)
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}{'AA' if signature[-2:] != 'AA' else 'BB'}"
    forged = jwt.encode({"sub": "PYTEST_MGR1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                        "another-secret-key-that-is-long-enough-123", algorithm="HS256")
    for bad in (tampered, forged, "not-a-token"):
        assert client.get("/auth/me", headers=bearer(bad)).status_code == 401
    assert client.get("/auth/me").status_code == 401


def test_inactive_account_is_403(client, db):
    token = token_for(client)
    db.execute(text("UPDATE managers SET is_active = FALSE WHERE manager_id = 'PYTEST_MGR1'"))
    db.commit()
    assert client.get("/auth/me", headers=bearer(token)).status_code == 403
    assert login(client).status_code == 403


def test_logout_is_ok(client):
    assert client.post("/auth/logout").json() == {"status": "ok"}


# ---------- protected API ----------
def test_protected_endpoints_need_a_token(client, db, monkeypatch):
    import app.services.llm_client as llm

    def no_llm(*args, **kwargs):
        raise RuntimeError("LLM disabled in tests")
    monkeypatch.setattr(llm.LLMClient, "generate", no_llm)   # Resource Agent falls back to its template

    order_id = db.execute(text("SELECT o.cus_ord_id FROM cust_ord_table o JOIN materials m "
                               "ON LOWER(TRIM(m.material_name)) = LOWER(TRIM(o.material_name)) "
                               "ORDER BY o.cus_ord_id DESC LIMIT 1")).scalar()
    db.rollback()
    calls = [
        ("get", "/orders", None),
        ("post", "/production/analyze", {"order_id": order_id}),
        ("get", "/risk/health", None),
        ("get", "/recommendation/kb", None),
    ]
    token = token_for(client)
    for method, path, body in calls:
        anonymous = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        assert anonymous.status_code == 401, path
        kwargs = {"headers": bearer(token), **({"json": body} if body else {})}
        assert getattr(client, method)(path, **kwargs).status_code == 200, path


def test_public_endpoints_stay_public(client):
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/").status_code == 200
