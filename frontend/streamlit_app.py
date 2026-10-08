"""
FabricFlow entry point and router.

Signed out: only Home, Sign In and Sign Up exist (no sidebar).
Signed in:  Dashboard, New Order, Orders, Delay Prediction, Recommendations in the sidebar,
            plus a top bar with the manager's details and Log out.
Run from the project folder:  streamlit run frontend/streamlit_app.py
"""
import streamlit as st

st.set_page_config(page_title="FabricFlow", page_icon="🧵", layout="wide", initial_sidebar_state="expanded")

import auth_ui  # noqa: E402
import layout  # noqa: E402
import theme  # noqa: E402

st.session_state[auth_ui.ROUTER_FLAG] = True
theme.inject_css()

HOME = st.Page("views/home.py", title="Home", icon=":material/home:", url_path="home", default=True)
SIGN_IN = st.Page("views/sign_in.py", title="Sign In", icon=":material/login:", url_path="sign_in")
SIGN_UP = st.Page("views/sign_up.py", title="Sign Up", icon=":material/person_add:", url_path="sign_up")

DASHBOARD = st.Page("views/dashboard.py", title="Dashboard", icon=":material/space_dashboard:",
                    url_path="dashboard", default=True)
NEW_ORDER = st.Page("pages/new_order.py", title="New Order", icon=":material/add_circle:", url_path="new_order")
ORDERS = st.Page("pages/orders.py", title="Orders", icon=":material/receipt_long:", url_path="orders")
DELAY = st.Page("pages/delay_prediction.py", title="Delay Prediction", icon=":material/schedule:",
                url_path="delay_prediction")
RECOMMENDATIONS = st.Page("pages/recommendation.py", title="Recommendations", icon=":material/lightbulb:",
                          url_path="recommendations")

manager, status = auth_ui.current_manager()

if status == "down":
    st.markdown(theme.brand_title(), unsafe_allow_html=True)
    st.error(f"The FabricFlow backend is not reachable at {auth_ui.API_URL}. "
             "Please start it (cd backend && uvicorn app.main:app --reload --port 8000) and refresh.")
    st.stop()

goto = st.session_state.pop("ff_goto", None)

if manager:
    page = st.navigation([DASHBOARD, NEW_ORDER, ORDERS, DELAY, RECOMMENDATIONS], position="sidebar")
    if goto == "dashboard":
        st.switch_page(DASHBOARD)
    layout.render_top_bar(manager)
    layout.render_sidebar_extras()
else:
    theme.inject_public_css()
    page = st.navigation([HOME, SIGN_IN, SIGN_UP], position="hidden")
    if goto == "home":
        st.switch_page(HOME)
    if goto == "sign_in":
        st.switch_page(SIGN_IN)

page.run()
