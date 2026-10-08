"""
Signed-in shell: sticky top bar with the user chip and Log out, plus sidebar extras.
The sidebar navigation itself comes from st.navigation in streamlit_app.py.
"""
import html
from datetime import datetime
from urllib.parse import quote

import streamlit as st

import auth_ui
import theme

# Sidebar brand drawn with CSS only (an inline-SVG data URI, no image file)
_SIDEBAR_BRAND_CSS = f"""
<style>
[data-testid="stSidebarNav"]::before, [data-testid="stSidebarNavItems"]::before {{
    content: "FABRICFLOW"; display: block; margin: .2rem .6rem 1rem .6rem; padding: .35rem 0 .35rem 46px;
    font-weight: 800; letter-spacing: .14em; color: {theme.TEXT}; font-size: .98rem;
    background: url("data:image/svg+xml,{quote(theme.LOGO_SVG)}") no-repeat left center / 34px 34px;
}}
[data-testid="stSidebarNavItems"]::before {{ content: none; }}
</style>
"""


def _format_time(value) -> str:
    if not value:
        return "first sign-in"
    try:
        return datetime.fromisoformat(str(value)).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return str(value)


def render_top_bar(manager: dict) -> None:
    manager_id = manager.get("manager_id", "")
    manager_type = manager.get("manager_type", "")
    email = manager.get("email", "")
    with st.container(key="ff_topbar"):
        brand, chip, details, logout = st.columns([3.2, 3.2, 1.1, 1.1], vertical_alignment="center")
        brand.markdown(theme.brand_title(), unsafe_allow_html=True)
        chip.markdown(
            f'<div class="ff-chip"><div class="ff-avatar">{html.escape(manager_id[:1] or "?")}</div>'
            f'<div><div class="ff-chip-id">{html.escape(manager_id)}</div>'
            f'<div class="ff-chip-type">{html.escape(manager_type)}</div></div></div>',
            unsafe_allow_html=True,
        )
        with details.popover("Details", width="stretch"):
            st.markdown(f"**{manager_id}**")
            st.caption(manager_type)
            st.write(f"✉️ {email}")
            st.caption(f"Last sign-in: {_format_time(manager.get('last_login_at'))}")
        if logout.button("Log out", key="ff_topbar_logout", width="stretch"):
            auth_ui.logout()
            st.session_state["ff_goto"] = "home"
            st.rerun()


def render_sidebar_extras() -> None:
    st.markdown(_SIDEBAR_BRAND_CSS, unsafe_allow_html=True)
    st.sidebar.markdown('<div class="ff-sidebar-footer">AI recommends.<br>The manager decides.</div>',
                        unsafe_allow_html=True)
