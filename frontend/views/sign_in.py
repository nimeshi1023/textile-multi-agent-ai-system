"""Public Sign In page (look only; the logic lives in auth_ui.py)."""
import streamlit as st

import auth_ui
import theme

AUTH_CARD_CSS = """
<style>
.block-container { max-width: 540px !important; padding-top: 2.4rem; }
.ff-auth-head { text-align: center; margin: .6rem 0 1.1rem 0; }
.ff-auth-head .ff-brand-row { justify-content: center; }
.ff-auth-head h2 { margin: 1.1rem 0 .2rem 0; font-size: 1.45rem; }
</style>
"""
st.markdown(AUTH_CARD_CSS, unsafe_allow_html=True)

st.page_link("views/home.py", label="Back to Home", icon=":material/arrow_back:")
st.markdown(f'<div class="ff-auth-head">{theme.brand_title()}<h2>Welcome back</h2>'
            '<div class="ff-muted">Sign in with your Manager ID</div></div>', unsafe_allow_html=True)

notice = auth_ui.pop_notice()
if notice:
    st.info(notice)

with st.container(key="ffcard_signin"):
    with st.form("ff_view_sign_in", border=False):
        manager_id = st.text_input("Manager ID", placeholder="e.g. MGR001", key="view_si_manager_id")
        password = st.text_input("Password", type="password", key="view_si_password")
        submitted = st.form_submit_button("Sign In", type="primary", width="stretch")
    if submitted:
        with st.spinner("Signing in..."):
            result = auth_ui.login(manager_id, password)
        if result["ok"]:
            st.session_state["ff_goto"] = "dashboard"
            st.rerun()
        auth_ui.show_login_result(result)

    st.markdown('<div class="ff-muted" style="text-align:center;margin-top:.6rem">New here?</div>',
                unsafe_allow_html=True)
    if st.button("Create an account – Sign Up", key="si_to_signup", type="tertiary", width="stretch"):
        st.switch_page("views/sign_up.py")
