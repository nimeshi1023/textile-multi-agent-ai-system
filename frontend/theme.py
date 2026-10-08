"""
FabricFlow visual theme: a dark, warm, neumorphic look.

inject_css() styles the whole app (including the existing pages, which are not edited),
and the helpers below return small HTML snippets for cards, badges and headings.
The palette is mirrored in .streamlit/config.toml.
"""
import html

import streamlit as st

# ---------- palette ----------
BG = "#2E2A26"
BG_END = "#3B3631"
SURFACE = "#433D37"
SURFACE_RAISED = "#4C453F"
BORDER = "#5A524A"
TEXT = "#F3EDE4"
MUTED = "#B9AFA3"
ACCENT = "#F0933A"
ACCENT_SOFT = "#C9B79C"
SUCCESS = "#6FBF8B"
WARNING = "#E8B04A"
DANGER = "#E5604D"

RISK_COLORS = {"Low": SUCCESS, "Medium": WARNING, "High": DANGER, "Unavailable": MUTED}
PRIORITY_COLORS = {"Low": SUCCESS, "Medium": WARNING, "High": DANGER, "Urgent": DANGER}
CHART_COLORS = [ACCENT, ACCENT_SOFT, "#E8B04A", "#8FA9A0", "#D97A5B", "#9C8F80"]
FONT_STACK = '"Poppins", "Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif'

# ---------- inline SVG icons (stroke = currentColor) ----------
def _svg(paths: str) -> str:
    return ('<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths}</svg>')


ICONS = {
    "order": _svg('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 3h6v3H9z"/><path d="M8.5 11h7M8.5 15h5"/>'),
    "factory": _svg('<path d="M3 21V10l5 3V10l5 3V7l8 4v10z"/><path d="M7 17h2M12 17h2M17 17h2"/>'),
    "clock": _svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    "bulb": _svg('<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>'),
    "book": _svg('<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5M8 7h7"/>'),
    "user_check": _svg('<circle cx="9" cy="8" r="4"/><path d="M3 21a6 6 0 0 1 12 0"/><path d="M16 11l2 2 4-4"/>'),
    "chart": _svg('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
    "calendar": _svg('<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>'),
    "flag": _svg('<path d="M5 21V4"/><path d="M5 4h11l-2 4 2 4H5"/>'),
    "layers": _svg('<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>'),
    "check": _svg('<path d="M20 6L9 17l-5-5"/>'),
    "alert": _svg('<path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17h.01"/>'),
}

LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="34" height="34" aria-hidden="true">'
    f'<rect x="1" y="1" width="38" height="38" rx="12" fill="{SURFACE_RAISED}" stroke="{BORDER}"/>'
    f'<g stroke-width="3.2" stroke-linecap="round"><path d="M11 13h18" stroke="{ACCENT}"/>'
    f'<path d="M11 20h18" stroke="{ACCENT_SOFT}"/><path d="M11 27h18" stroke="{ACCENT}"/>'
    f'<path d="M15 9v22" stroke="{ACCENT_SOFT}" opacity=".8"/><path d="M25 9v22" stroke="{ACCENT_SOFT}" opacity=".8"/></g>'
    "</svg>"
)

# ---------- global CSS ----------
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {{ font-family: {FONT_STACK}; }}
.stApp {{ background: linear-gradient(180deg, {BG} 0%, {BG_END} 100%); color: {TEXT}; }}
[data-testid="stHeader"] {{ background: transparent; }}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stMainMenu"], [data-testid="stAppDeployButton"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"] {{ display: none !important; visibility: hidden; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1280px; }}
h1, h2, h3, h4 {{ color: {TEXT}; letter-spacing: -0.01em; }}
a {{ color: {ACCENT}; }}
hr {{ border-color: {BORDER}; }}

/* ---- neumorphic cards ---- */
.ff-card, [class*="st-key-ffcard"] {{
    background: linear-gradient(145deg, {SURFACE_RAISED}, {SURFACE});
    border: 1px solid rgba(90,82,74,0.65); border-radius: 24px;
    box-shadow: 8px 10px 22px rgba(0,0,0,0.38), -5px -5px 14px rgba(255,240,220,0.035);
}}
.ff-card {{ padding: 1.25rem 1.35rem; height: 100%; }}
[class*="st-key-ffcard"] {{ padding: 1.1rem 1.15rem 0.6rem 1.15rem; }}
.ff-section {{ text-transform: uppercase; letter-spacing: 0.18em; font-size: 0.8rem; font-weight: 700;
               color: {MUTED}; margin: 1.8rem 0 0.9rem 0; display: flex; align-items: center; gap: .7rem; }}
.ff-section::after {{ content: ""; flex: 1; height: 1px; background: linear-gradient(90deg, {BORDER}, transparent); }}
.ff-card-title {{ text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.74rem; font-weight: 700;
                  color: {MUTED}; margin-bottom: .35rem; }}
.ff-muted {{ color: {MUTED}; }}
.ff-empty {{ color: {MUTED}; text-align: center; padding: 2.2rem 0.5rem; font-size: 0.92rem; }}

/* ---- buttons: orange pill (primary), cream outline (secondary) ---- */
.stButton > button, .stFormSubmitButton > button, .stPageLink a, [data-testid="stPopover"] > div > button,
[data-testid^="stBaseButton"] {{
    border-radius: 999px !important; font-weight: 600; letter-spacing: 0.02em; transition: all .15s ease;
}}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
    background: {ACCENT} !important; color: #2A211A !important; border: 1px solid {ACCENT} !important;
    box-shadow: 0 6px 16px rgba(240,147,58,0.28);
}}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
    background: #F5A458 !important; border-color: #F5A458 !important; transform: translateY(-1px);
}}
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"] {{
    background: transparent !important; color: {TEXT} !important; border: 1.5px solid rgba(243,237,228,0.55) !important;
}}
[data-testid="stBaseButton-secondary"]:hover, [data-testid="stBaseButton-secondaryFormSubmit"]:hover {{
    border-color: {ACCENT} !important; color: {ACCENT} !important;
}}
[data-testid="stBaseButton-tertiary"] {{ color: {ACCENT} !important; }}

/* ---- inputs ---- */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{
    background: {SURFACE} !important; border-radius: 14px !important; border-color: {BORDER} !important;
}}
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within, [data-baseweb="textarea"]:focus-within {{
    border-color: {ACCENT} !important; box-shadow: 0 0 0 3px rgba(240,147,58,0.28) !important;
}}
input, textarea {{ color: {TEXT} !important; caret-color: {ACCENT}; }}
label, [data-testid="stWidgetLabel"] p {{ color: {MUTED} !important; font-weight: 500; }}

/* ---- tabs, expander, metric, alerts, dataframe, popover ---- */
[data-baseweb="tab-list"] {{ gap: .4rem; }}
button[data-baseweb="tab"] {{ border-radius: 999px; padding: .35rem 1rem; color: {MUTED}; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: {ACCENT}; background: rgba(240,147,58,0.10); }}
[data-baseweb="tab-highlight"] {{ background-color: {ACCENT}; }}
[data-testid="stExpander"] details {{ border-radius: 18px; border-color: {BORDER}; background: rgba(67,61,55,0.55); }}
[data-testid="stMetric"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 20px; padding: .8rem 1rem; }}
[data-testid="stMetricValue"] {{ color: {TEXT}; }}
[data-testid="stAlert"], [data-testid="stAlertContainer"] {{ border-radius: 16px; }}
/* st.info in the warm palette (Streamlit's default is blue) */
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
    background: rgba(201,183,156,0.14) !important; border: 1px solid rgba(201,183,156,0.30);
}}
[data-testid="stAlertContentInfo"], [data-testid="stAlertContentInfo"] p {{ color: {ACCENT_SOFT} !important; }}
[data-testid="stDataFrame"], [data-testid="stTable"] {{ border-radius: 16px; overflow: hidden; border: 1px solid {BORDER}; }}
[data-testid="stPopoverBody"] {{ background: {SURFACE_RAISED}; border: 1px solid {BORDER}; border-radius: 18px; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 22px; border-color: {BORDER}; }}

/* ---- sidebar ---- */
[data-testid="stSidebar"] {{ background: linear-gradient(180deg, #37322D, {BG}); border-right: 1px solid {BORDER}; }}
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavLink"] {{ border-radius: 999px; margin: 2px 6px; padding: .45rem .9rem; }}
[data-testid="stSidebarNav"] a span, [data-testid="stSidebarNavLink"] span {{ color: {MUTED}; font-weight: 500; }}
[data-testid="stSidebarNav"] a:hover, [data-testid="stSidebarNavLink"]:hover {{ background: rgba(240,147,58,0.10); }}
[data-testid="stSidebarNav"] a[aria-current="page"], [data-testid="stSidebarNavLink"][aria-current="page"] {{
    background: {ACCENT}; box-shadow: 0 6px 16px rgba(240,147,58,0.25);
}}
[data-testid="stSidebarNav"] a[aria-current="page"] span, [data-testid="stSidebarNavLink"][aria-current="page"] span {{
    color: #2A211A !important; font-weight: 700;
}}
.ff-sidebar-footer {{ color: {MUTED}; font-size: .78rem; text-align: center; margin-top: .6rem; }}

/* ---- top bar (signed in) ---- */
.st-key-ff_topbar {{
    position: sticky; top: 0.4rem; z-index: 50; background: rgba(52,47,42,0.92); backdrop-filter: blur(8px);
    border: 1px solid {BORDER}; border-radius: 22px; padding: .55rem 1rem;
    box-shadow: 6px 8px 20px rgba(0,0,0,0.35), -4px -4px 12px rgba(255,240,220,0.03); margin-bottom: 1.2rem;
}}
.ff-brand-row {{ display: flex; align-items: center; gap: .65rem; }}
.ff-brand-name {{ font-weight: 800; letter-spacing: .12em; text-transform: uppercase; color: {TEXT}; font-size: 1.05rem; line-height: 1.1; }}
.ff-brand-name span {{ color: {ACCENT}; }}
.ff-brand-sub {{ color: {MUTED}; font-size: .74rem; letter-spacing: .06em; }}
.ff-chip {{ display: flex; align-items: center; gap: .6rem; justify-content: flex-end; }}
.ff-avatar {{ width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center; flex: none;
              background: linear-gradient(145deg, {ACCENT}, #D9792A); color: #2A211A; font-weight: 800; }}
.ff-chip-id {{ font-weight: 700; color: {TEXT}; line-height: 1.1; }}
.ff-chip-type {{ color: {MUTED}; font-size: .78rem; }}

/* ---- badges ---- */
.ff-badge {{ display: inline-block; padding: .18rem .7rem; border-radius: 999px; font-size: .78rem; font-weight: 700;
             color: #2A211A; letter-spacing: .03em; }}

/* ---- KPI cards ---- */
.ff-kpi {{ display: flex; align-items: center; gap: .9rem; }}
.ff-kpi-icon {{ width: 50px; height: 50px; border-radius: 16px; display: grid; place-items: center; flex: none;
                color: {ACCENT}; background: {SURFACE};
                box-shadow: inset 3px 3px 7px rgba(0,0,0,0.35), inset -3px -3px 7px rgba(255,240,220,0.04); }}
.ff-kpi-value {{ font-size: 1.9rem; font-weight: 800; color: {TEXT}; line-height: 1.05; }}
.ff-kpi-label {{ text-transform: uppercase; letter-spacing: .12em; font-size: .7rem; color: {MUTED}; font-weight: 700; }}
.ff-kpi-hint {{ color: {MUTED}; font-size: .78rem; }}

/* ---- phones ---- */
@media (max-width: 640px) {{
    .block-container {{ padding-left: .9rem; padding-right: .9rem; padding-top: 1rem; }}
    .ff-kpi-value {{ font-size: 1.5rem; }}
    .st-key-ff_topbar {{ position: static; border-radius: 18px; }}
    .ff-chip {{ justify-content: flex-start; }}
}}
</style>
"""

# Signed out: no sidebar at all
PUBLIC_CSS = """
<style>
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"] { display: none !important; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def inject_public_css() -> None:
    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)


# ---------- HTML helpers ----------
def _e(value) -> str:
    return html.escape(str(value))


def brand_title(subtitle: str = "Textile Multi Agent AI") -> str:
    return (f'<div class="ff-brand-row">{LOGO_SVG}<div><div class="ff-brand-name">Fabric<span>Flow</span></div>'
            f'<div class="ff-brand-sub">{_e(subtitle)}</div></div></div>')


def section_title(text: str, anchor: str = "") -> str:
    anchor_attr = f' id="{_e(anchor)}"' if anchor else ""
    return f'<div class="ff-section"{anchor_attr}>{_e(text)}</div>'


def card_title(text: str) -> str:
    return f'<div class="ff-card-title">{_e(text)}</div>'


def feature_card(icon: str, title: str, text: str) -> str:
    return (f'<div class="ff-card ff-feature"><div class="ff-kpi-icon">{ICONS.get(icon, "")}</div>'
            f'<div style="font-weight:700;font-size:1.02rem;margin:.9rem 0 .35rem 0;color:{TEXT}">{_e(title)}</div>'
            f'<div class="ff-muted" style="font-size:.9rem;line-height:1.5">{_e(text)}</div></div>')


def info_tile(icon: str, label: str) -> str:
    return (f'<div class="ff-card" style="text-align:center;padding:1rem .6rem;border-radius:22px">'
            f'<div class="ff-kpi-icon" style="margin:0 auto .55rem auto">{ICONS.get(icon, "")}</div>'
            f'<div style="font-size:.86rem;font-weight:600;color:{TEXT}">{_e(label)}</div></div>')


def flow_steps(steps: list) -> str:
    pills = []
    for i, step in enumerate(steps):
        highlight = i in (0, len(steps) - 1)
        style = (f"background:{ACCENT};color:#2A211A;border-color:{ACCENT}" if highlight
                 else f"background:{SURFACE_RAISED};color:{TEXT};border-color:{BORDER}")
        pills.append(f'<span class="ff-step" style="{style}">{_e(step)}</span>')
    arrow = f'<span class="ff-step-arrow" style="color:{ACCENT}">→</span>'
    return (
        "<style>.ff-flow{display:flex;flex-wrap:wrap;gap:.55rem;align-items:center;justify-content:center}"
        ".ff-step{border:1px solid;border-radius:999px;padding:.55rem 1.05rem;font-weight:600;font-size:.88rem;"
        "box-shadow:4px 6px 14px rgba(0,0,0,.3)}.ff-step-arrow{font-weight:800}</style>"
        f'<div class="ff-flow">{arrow.join(pills)}</div>'
    )


def kpi_card(label: str, value, hint: str = "", icon: str = "chart") -> str:
    return (f'<div class="ff-card ff-kpi"><div class="ff-kpi-icon">{ICONS.get(icon, "")}</div><div>'
            f'<div class="ff-kpi-label">{_e(label)}</div><div class="ff-kpi-value">{_e(value)}</div>'
            f'<div class="ff-kpi-hint">{_e(hint)}</div></div></div>')


def badge(text: str, color: str) -> str:
    return f'<span class="ff-badge" style="background:{color}">{_e(text)}</span>'


def risk_badge(level: str) -> str:
    return badge(f"{level.upper()} RISK" if level in ("Low", "Medium", "High") else level, RISK_COLORS.get(level, MUTED))


def priority_badge(priority: str) -> str:
    return badge(priority, PRIORITY_COLORS.get(priority, MUTED))


def empty_state(text: str = "No data yet") -> str:
    return f'<div class="ff-empty">{_e(text)}</div>'


# ---------- charts ----------
def style_figure(fig, height: int = 300):
    """Plotly theme: transparent, cream text, orange/beige series, soft grid, no mode bar."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_STACK, color=TEXT, size=13), colorway=CHART_COLORS,
        margin=dict(l=8, r=8, t=8, b=8), height=height,
        legend=dict(orientation="h", y=-0.12, x=0.5, xanchor="center", font=dict(color=MUTED)),
        hoverlabel=dict(bgcolor=SURFACE_RAISED, bordercolor=BORDER, font=dict(color=TEXT, family=FONT_STACK)),
        bargap=0.35,
    )
    axis = dict(gridcolor="rgba(185,175,163,0.10)", zeroline=False, linecolor=BORDER,
                tickfont=dict(color=MUTED), title_font=dict(color=MUTED))
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}
