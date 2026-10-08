"""
Smoke tests for the Streamlit UI (router, public pages, signed-in shell, dashboard).

Uses Streamlit's AppTest on frontend/streamlit_app.py. The backend is replaced by a
fake HTTP layer, so these tests need no running server.
Run from the backend folder:  python -m pytest tests/test_frontend_ui.py -v
"""
import time
from pathlib import Path

import httpx
import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
APP = str(FRONTEND / "streamlit_app.py")

MANAGER = {"manager_id": "MGR_UI", "manager_type": "Supply Chain Manager", "email": "mgr.ui@fabricflow.example.com",
           "created_at": "2026-10-08T09:00:00+00:00", "last_login_at": "2026-10-08T10:00:00+00:00"}
SUMMARY = {
    "total_orders": 3, "high_priority_orders": 1, "orders_due_within_7_days": 1,
    "orders_by_priority": [{"label": "Medium", "count": 2}, {"label": "High", "count": 1}],
    "orders_by_product_type": [{"label": "Trousers", "count": 3}],
    "orders_by_material": [{"label": "Silk Thread", "count": 3}],
    "orders_per_day": [{"date": time.strftime("%Y-%m-%d"), "count": 3}],
    "deadlines_next_14_days": [{"order_id": "ORD-1", "product_type": "Trousers", "quantity": 100,
                                "priority": "High", "deadline_date": "2026-10-15", "days_left": 7}],
    "historical_delay_rate_by_product": [{"label": "Polo Shirt", "rate": 0.44, "orders": 301}],
    "top_delay_reasons": [{"label": "Material shortage", "count": 1435}],
    "decisions_by_type": [{"label": "approved", "count": 2}], "decisions_total": 2, "generated_at": "now",
}
EMPTY_SUMMARY = {**{k: [] for k in SUMMARY if isinstance(SUMMARY[k], list)}, "total_orders": 0,
                 "high_priority_orders": 0, "orders_due_within_7_days": 0, "decisions_total": 0, "generated_at": "now"}
ORDERS = [{"cus_ord_id": "ORD-1", "product_type": "Trousers", "quantity": 100, "priority": "High",
           "order_date": "2026-10-08", "deadline_date": "2026-10-15", "material_required": 73.0,
           "material_name": "Silk Thread"}]


class FakeBackend:
    def __init__(self, me_status=200, summary=SUMMARY, down=False):
        self.me_status, self.summary, self.down, self.calls = me_status, summary, down, []

    def _reply(self, method, url, **kwargs):
        self.calls.append((method, url))
        if self.down:
            raise httpx.ConnectError("backend down")
        path = url.split("8000", 1)[-1].split("?")[0]
        routes = {
            ("GET", "/auth/me"): (self.me_status, MANAGER),
            ("GET", "/auth/manager-types"): (200, {"manager_types": ["Production Manager", "Supply Chain Manager"]}),
            ("POST", "/auth/logout"): (200, {"status": "ok"}),
            ("GET", "/dashboard/summary"): (200, self.summary),
            ("GET", "/orders"): (200, ORDERS if self.summary is SUMMARY else []),
            ("GET", "/risk/model-info"): (503, {"detail": "Model not trained."}),
            ("GET", "/recommendation/kb"): (503, {"detail": "index not built"}),
        }
        status, body = routes.get((method, path), (200, []))
        return httpx.Response(status, json=body, request=httpx.Request(method, url))

    def get(self, url, **kwargs):
        return self._reply("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._reply("POST", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._reply("DELETE", url, **kwargs)


@pytest.fixture
def backend(monkeypatch):
    fake = FakeBackend()
    for name in ("get", "post", "delete"):
        monkeypatch.setattr(httpx, name, getattr(fake, name))
    return fake


def signed_in(at: AppTest) -> AppTest:
    at.session_state["auth_token"] = "fake.jwt.token"
    at.session_state["auth_manager"] = MANAGER
    at.session_state["auth_expires_at"] = time.time() + 3600
    return at


def markdown_text(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


# ---------- public pages ----------
def test_home_renders_without_sidebar(backend):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    text = markdown_text(at)
    assert "FABRICFLOW" in text and "Textile Multi Agent AI" in text
    assert "THE FOUR AGENTS".lower() in text.lower() and "How it works".lower() in text.lower()
    assert not at.sidebar.children                                 # nothing in the sidebar when signed out
    assert [b.label for b in at.button] == ["Sign In", "Sign Up", "Sign In", "Sign Up"]
    assert not any(c[1].endswith("/auth/me") for c in backend.calls)   # no token -> no backend call


def test_sign_in_and_sign_up_pages_render(backend):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.switch_page("views/sign_in.py").run()
    assert not at.exception
    assert [t.label for t in at.text_input] == ["Manager ID", "Password"]
    at.switch_page("views/sign_up.py").run()
    assert not at.exception
    assert [t.label for t in at.text_input] == ["Manager ID", "Email", "Password", "Confirm Password"]
    assert at.selectbox[0].options == ["Production Manager", "Supply Chain Manager"]


@pytest.mark.parametrize("page", ["pages/new_order.py", "pages/orders.py", "pages/delay_prediction.py",
                                  "pages/recommendation.py", "views/dashboard.py"])
def test_protected_pages_are_not_registered_without_token(backend, page):
    at = AppTest.from_file(APP, default_timeout=60).run()
    # Signed out, the router registers only Home / Sign In / Sign Up, so the page cannot be opened
    with pytest.raises(ValueError, match="Could not find a navigation page"):
        at.switch_page(page)
    assert "FABRICFLOW" in markdown_text(at)


# ---------- signed-in shell ----------
def test_signed_in_shell_shows_top_bar_and_dashboard(backend):
    at = signed_in(AppTest.from_file(APP, default_timeout=60)).run()
    assert not at.exception
    text = markdown_text(at)
    assert "MGR_UI" in text and "Supply Chain Manager" in text        # user chip
    assert any("mgr.ui@fabricflow.example.com" in m.value for m in at.markdown)   # email in Details popover
    assert "Welcome back, MGR_UI" in text
    assert "AI recommends.<br>The manager decides." in text           # sidebar footer
    assert "Log out" in [b.label for b in at.button]
    assert len(at.get("plotly_chart")) >= 5                           # the dashboard charts


@pytest.mark.parametrize("button, title", [
    ("New Order", "New Order"), ("Delay Prediction", "Delay Prediction"), ("Recommendations", "Recommendations"),
])
def test_existing_pages_open_inside_the_shell(backend, button, title):
    # Navigate the way a manager does (dashboard quick action -> st.switch_page through the router)
    at = signed_in(AppTest.from_file(APP, default_timeout=60)).run()
    next(b for b in at.button if b.key == f"quick_{button}").click().run()
    assert not at.exception
    assert title in [t.value for t in at.title]
    assert "MGR_UI" in markdown_text(at)                               # top bar on the existing page
    assert "ff_logout" not in [b.key for b in at.button]               # old sidebar user box is off
    assert "Log out" in [b.label for b in at.button]


def test_orders_page_is_registered_when_signed_in(backend):
    at = signed_in(AppTest.from_file(APP, default_timeout=60)).run()
    at.switch_page("pages/orders.py").run()                            # raises if not registered
    assert not at.exception
    assert "Orders" in [t.value for t in at.title]


def test_dashboard_empty_data_shows_friendly_states(monkeypatch):
    fake = FakeBackend(summary=EMPTY_SUMMARY)
    for name in ("get", "post", "delete"):
        monkeypatch.setattr(httpx, name, getattr(fake, name))
    at = signed_in(AppTest.from_file(APP, default_timeout=60)).run()
    assert not at.exception
    assert markdown_text(at).count("No data yet") >= 5
    assert "No deadlines in the next 14 days" in markdown_text(at)


def test_logout_returns_to_home(backend):
    at = signed_in(AppTest.from_file(APP, default_timeout=60)).run()
    next(b for b in at.button if b.label == "Log out").click().run()
    assert not at.exception
    assert "auth_token" not in at.session_state
    assert "FABRICFLOW" in markdown_text(at) and "Welcome back" not in markdown_text(at)


def test_expired_session_goes_to_sign_in(monkeypatch):
    fake = FakeBackend(me_status=401)
    for name in ("get", "post", "delete"):
        monkeypatch.setattr(httpx, name, getattr(fake, name))
    at = signed_in(AppTest.from_file(APP, default_timeout=60)).run()
    assert not at.exception
    assert "auth_token" not in at.session_state
    assert [t.label for t in at.text_input] == ["Manager ID", "Password"]
    assert "Your session has expired. Please sign in again." in [i.value for i in at.info]


def test_backend_down_while_signed_in_shows_error_card(monkeypatch):
    fake = FakeBackend(down=True)
    for name in ("get", "post", "delete"):
        monkeypatch.setattr(httpx, name, getattr(fake, name))
    at = signed_in(AppTest.from_file(APP, default_timeout=60)).run()
    assert not at.exception
    assert any("backend is not reachable" in e.value for e in at.error)
