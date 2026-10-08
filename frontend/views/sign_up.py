"""Public Sign Up page (look only; the logic lives in auth_ui.py)."""
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
st.markdown(f'<div class="ff-auth-head">{theme.brand_title()}<h2>Create your account</h2>'
            '<div class="ff-muted">For production, factory and supply chain managers</div></div>',
            unsafe_allow_html=True)

with st.container(key="ffcard_signup"):
    types = auth_ui.fetch_manager_types()
    if not types:
        st.error(f"Cannot reach the FabricFlow backend at {auth_ui.API_URL}. Please make sure it is running.")
        st.stop()

    manager_type = st.selectbox("Manager Type", types, key="view_su_type")
    manager_id = st.text_input("Manager ID", placeholder="e.g. MGR001", key="view_su_manager_id",
                               help="4-20 characters: letters, digits, underscore or hyphen")
    email = st.text_input("Email", placeholder="name@company.com", key="view_su_email")
    password = st.text_input("Password", type="password", key="view_su_password")
    confirm = st.text_input("Confirm Password", type="password", key="view_su_confirm")
    st.markdown(auth_ui.password_checklist_html(password, confirm, ok_color=theme.SUCCESS), unsafe_allow_html=True)

    if st.button("Create Account", type="primary", width="stretch", key="view_su_submit"):
        with st.spinner("Creating your account..."):
            st.session_state["ff_signup_result"] = auth_ui.signup(manager_type, manager_id, email, password, confirm)

    result = st.session_state.get("ff_signup_result")
    if result:
        auth_ui.show_signup_result(result)
        if result["ok"] and st.button("Go to Sign In", key="su_go_signin", width="stretch"):
            st.session_state.pop("ff_signup_result", None)
            st.switch_page("views/sign_in.py")

    st.markdown('<div class="ff-muted" style="text-align:center;margin-top:.6rem">Already have an account?</div>',
                unsafe_allow_html=True)
    if st.button("Sign In", key="su_to_signin", type="tertiary", width="stretch"):
        st.session_state.pop("ff_signup_result", None)
        st.switch_page("views/sign_in.py")
