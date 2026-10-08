"""
Shared sign-in helpers for every FabricFlow page.

    from auth_ui import require_login, auth_headers, render_user_sidebar
    require_login()          # shows the Sign In / Sign Up screen and stops if not signed in
    render_user_sidebar()    # manager box + Logout in the sidebar
    httpx.get(url, headers=auth_headers())

The access token lives only in st.session_state (never in the URL), so refreshing
the browser starts a new session and the manager signs in again.
"""
import html
import re
import time

import httpx
import streamlit as st

API_URL = "http://localhost:8000"

TOKEN_KEY = "auth_token"
MANAGER_KEY = "auth_manager"
EXPIRES_KEY = "auth_expires_at"
NOTICE_KEY = "auth_notice"

FIELD_LABELS = {
    "manager_type": "Manager Type",
    "manager_id": "Manager ID",
    "email": "Email",
    "password": "Password",
    "confirm_password": "Confirm Password",
}
MANAGER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LOGO_SVG = """
<svg width="52" height="52" viewBox="0 0 52 52" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="2" y="2" width="48" height="48" rx="12" fill="#1F2A5A"/>
  <g stroke-width="4" stroke-linecap="round">
    <path d="M14 16 H38" stroke="#E0A030"/><path d="M14 26 H38" stroke="#C7CDEB"/><path d="M14 36 H38" stroke="#E0A030"/>
    <path d="M18 12 V40" stroke="#C7CDEB" opacity="0.85"/><path d="M26 12 V40" stroke="#E0A030" opacity="0.85"/>
    <path d="M34 12 V40" stroke="#C7CDEB" opacity="0.85"/>
  </g>
</svg>
"""

# Shared styles: deep indigo primary, warm marigold accent. Colours that sit on the
# page use semi-transparent values, so the screen stays readable in light and dark themes.
BASE_CSS = """
<style>
  button[kind="primary"], button[kind="primaryFormSubmit"] {
      background: #1F2A5A; border: 1px solid rgba(224,160,48,0.55); color: #ffffff;
      border-radius: 10px; font-weight: 600; transition: background .15s ease;
  }
  button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {
      background: #2C3C80; border-color: #E0A030; color: #ffffff;
  }
  .ff-user-card {
      border: 1px solid rgba(127,127,127,0.25); border-left: 4px solid #E0A030;
      border-radius: 12px; padding: 0.7rem 0.85rem; margin: 0.25rem 0 0.75rem 0;
      background: rgba(31,42,90,0.06);
  }
  .ff-user-card .ff-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: .06em; opacity: .65; }
  .ff-user-card .ff-id { font-size: 1.05rem; font-weight: 700; }
  .ff-user-card .ff-type { font-size: 0.85rem; opacity: .85; }
</style>
"""

AUTH_PAGE_CSS = """
<style>
  /* Signed out: no sidebar, so no other page is visible or clickable */
  section[data-testid="stSidebar"], [data-testid="stSidebarNav"],
  [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"],
  [data-testid="collapsedControl"] { display: none !important; }

  [data-testid="stAppViewContainer"] {
      background:
        radial-gradient(1100px 500px at 50% -10%, rgba(31,42,90,0.16), transparent 70%),
        radial-gradient(600px 300px at 100% 100%, rgba(224,160,48,0.10), transparent 70%);
  }
  .block-container { max-width: 480px; padding-top: 3.5rem; }

  .ff-brand { text-align: center; margin-bottom: 1.1rem; }
  .ff-brand h1 { font-size: 2.1rem; font-weight: 800; letter-spacing: -0.02em; margin: 0.4rem 0 0.1rem 0; padding: 0; }
  .ff-brand h1 span { color: #E0A030; }
  .ff-brand p { opacity: 0.75; margin: 0; font-size: 0.98rem; }
  .ff-weave { height: 4px; width: 84px; margin: 0.8rem auto 0 auto; border-radius: 4px;
              background: repeating-linear-gradient(90deg, #1F2A5A 0 12px, #E0A030 12px 24px); }

  [data-testid="stVerticalBlockBorderWrapper"] {
      border-radius: 16px !important; border-color: rgba(127,127,127,0.22) !important;
      box-shadow: 0 10px 30px rgba(15,23,42,0.10); background: rgba(127,127,127,0.04);
  }
  .ff-check { font-size: 0.86rem; line-height: 1.7; margin: -0.25rem 0 0.5rem 0.1rem; }
  .ff-ok { color: #2e7d32; font-weight: 600; }
  .ff-todo { opacity: 0.6; }
  .ff-footer { text-align: center; font-size: 0.78rem; opacity: 0.55; margin-top: 1rem; }
</style>
"""


# ---------- session ----------
def auth_headers() -> dict:
    token = st.session_state.get(TOKEN_KEY)
    return {"Authorization": f"Bearer {token}"} if token else {}


def _clear_session() -> None:
    for key in (TOKEN_KEY, MANAGER_KEY, EXPIRES_KEY):
        st.session_state.pop(key, None)


def require_login() -> dict:
    """Return the signed-in manager, or show the Sign In / Sign Up screen and stop."""
    st.markdown(BASE_CSS, unsafe_allow_html=True)
    token = st.session_state.get(TOKEN_KEY)
    if token and time.time() >= st.session_state.get(EXPIRES_KEY, 0):
        _clear_session()
        st.session_state[NOTICE_KEY] = "Your session has expired. Please sign in again."
    elif token:
        try:
            response = httpx.get(f"{API_URL}/auth/me", headers=auth_headers(), timeout=10.0)
        except httpx.HTTPError:
            st.error(f"The FabricFlow backend is not reachable at {API_URL}. Please start it and refresh.")
            st.stop()
        if response.status_code == 200:
            st.session_state[MANAGER_KEY] = response.json()
            return response.json()
        _clear_session()
        st.session_state[NOTICE_KEY] = (
            "This account has been deactivated." if response.status_code == 403
            else "Your session has expired. Please sign in again."
        )
    render_auth_page()
    st.stop()


def render_user_sidebar() -> None:
    manager = st.session_state.get(MANAGER_KEY)
    if not manager:
        return
    with st.sidebar:
        st.markdown(
            f"""<div class="ff-user-card">
                  <div class="ff-label">Signed in as</div>
                  <div class="ff-id">{html.escape(manager['manager_id'])}</div>
                  <div class="ff-type">{html.escape(manager['manager_type'])}</div>
                </div>""",
            unsafe_allow_html=True,
        )
        if st.button("Log out", key="ff_logout", width="stretch"):
            try:
                httpx.post(f"{API_URL}/auth/logout", headers=auth_headers(), timeout=5.0)
            except httpx.HTTPError:
                pass   # stateless logout: deleting the token is what matters
            _clear_session()
            st.session_state[NOTICE_KEY] = "You have been signed out."
            st.rerun()


# ---------- the Sign In / Sign Up screen ----------
def render_auth_page() -> None:
    st.markdown(AUTH_PAGE_CSS, unsafe_allow_html=True)
    st.markdown(
        f"""<div class="ff-brand">{LOGO_SVG}
              <h1>Fabric<span>Flow</span></h1>
              <p>Multi-Agent AI for Textile Production</p>
              <div class="ff-weave"></div>
            </div>""",
        unsafe_allow_html=True,
    )
    notice = st.session_state.pop(NOTICE_KEY, None)
    if notice:
        st.info(notice)

    with st.container(border=True):
        sign_in, sign_up = st.tabs(["Sign In", "Sign Up"])
        with sign_in:
            _sign_in_form()
        with sign_up:
            _sign_up_form()
    st.markdown("<div class='ff-footer'>Managers only · Your session ends when the browser tab is refreshed</div>",
                unsafe_allow_html=True)


def _sign_in_form() -> None:
    with st.form("ff_sign_in", border=False):
        manager_id = st.text_input("Manager ID", placeholder="e.g. MGR001", key="si_manager_id")
        password = st.text_input("Password", type="password", key="si_password")
        submitted = st.form_submit_button("Sign In", type="primary", width="stretch")
    if not submitted:
        return
    if not manager_id.strip() or not password:
        st.error("Please enter your Manager ID and password.")
        return
    try:
        with st.spinner("Signing in..."):
            response = httpx.post(f"{API_URL}/auth/login",
                                  json={"manager_id": manager_id.strip(), "password": password}, timeout=15.0)
    except httpx.HTTPError:
        st.error(f"Cannot reach the FabricFlow backend at {API_URL}. Please make sure it is running.")
        return

    if response.status_code == 200:
        body = response.json()
        st.session_state[TOKEN_KEY] = body["access_token"]
        st.session_state[MANAGER_KEY] = body["manager"]
        st.session_state[EXPIRES_KEY] = time.time() + body["expires_in"] - 30
        st.rerun()
    elif response.status_code == 429:
        st.warning("🔒 " + _detail(response) + " This protects your account from password guessing.")
    elif response.status_code == 403:
        st.error("This account has been deactivated. Please contact your administrator.")
    elif response.status_code == 401:
        st.error("Invalid Manager ID or password.")
    else:
        st.error(f"Sign in failed: {_detail(response)}")


def _manager_types() -> list:
    if "ff_manager_types" not in st.session_state:
        try:
            response = httpx.get(f"{API_URL}/auth/manager-types", timeout=10.0)
            response.raise_for_status()
            st.session_state.ff_manager_types = response.json()["manager_types"]
        except httpx.HTTPError:
            return []
    return st.session_state.ff_manager_types


def _sign_up_form() -> None:
    types = _manager_types()
    if not types:
        st.error(f"Cannot reach the FabricFlow backend at {API_URL}. Please make sure it is running.")
        return
    manager_type = st.selectbox("Manager Type", types, key="su_type")
    manager_id = st.text_input("Manager ID", placeholder="e.g. MGR001", key="su_manager_id",
                               help="4-20 characters: letters, digits, underscore or hyphen")
    email = st.text_input("Email", placeholder="name@company.com", key="su_email")
    password = st.text_input("Password", type="password", key="su_password")
    confirm = st.text_input("Confirm Password", type="password", key="su_confirm")

    checks = [
        ("At least 8 characters", len(password) >= 8),
        ("An uppercase letter", bool(re.search(r"[A-Z]", password))),
        ("A lowercase letter", bool(re.search(r"[a-z]", password))),
        ("A digit", bool(re.search(r"\d", password))),
        ("Passwords match", bool(password) and password == confirm),
    ]
    st.markdown(
        "<div class='ff-check'>" + "<br>".join(
            f"<span class='{'ff-ok' if ok else 'ff-todo'}'>{'✓' if ok else '○'} {label}</span>"
            for label, ok in checks) + "</div>",
        unsafe_allow_html=True,
    )

    if not st.button("Create Account", type="primary", width="stretch", key="su_submit"):
        return
    problems = []
    if not MANAGER_ID_RE.match(manager_id.strip()):
        problems.append("Manager ID: 4-20 characters, letters, digits, underscore or hyphen.")
    if not EMAIL_RE.match(email.strip()):
        problems.append("Email: please enter a valid email address.")
    if not all(ok for _, ok in checks[:4]):
        problems.append("Password: at least 8 characters with an uppercase letter, a lowercase letter and a digit.")
    if password != confirm:
        problems.append("Confirm Password: passwords do not match.")
    if problems:
        st.error("\n".join(f"- {p}" for p in problems))
        return

    payload = {"manager_type": manager_type, "manager_id": manager_id.strip(), "email": email.strip(),
               "password": password, "confirm_password": confirm}
    try:
        with st.spinner("Creating your account..."):
            response = httpx.post(f"{API_URL}/auth/signup", json=payload, timeout=15.0)
    except httpx.HTTPError:
        st.error(f"Cannot reach the FabricFlow backend at {API_URL}. Please make sure it is running.")
        return

    if response.status_code == 201:
        created = response.json()
        st.success(f"Account **{created['manager_id']}** created. Go to the **Sign In** tab to sign in.")
    elif response.status_code == 409:
        st.error(response.json()["detail"]["message"] + ".")
    elif response.status_code == 422:
        st.error("\n".join(f"- {line}" for line in _field_errors(response)))
    else:
        st.error(f"Sign up failed: {_detail(response)}")


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        return response.text
    return detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)


def _field_errors(response: httpx.Response) -> list:
    lines = []
    for err in response.json().get("detail", []):
        field = FIELD_LABELS.get(err.get("loc", [""])[-1], "Form")
        lines.append(f"{field}: {str(err.get('msg', '')).removeprefix('Value error, ')}")
    return lines
