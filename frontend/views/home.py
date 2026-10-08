"""Public Home page (no sign-in needed)."""
import streamlit as st

import auth_ui
import theme

HERO_CSS = f"""
<style>
.ff-nav-links {{ display: flex; gap: 1.4rem; justify-content: flex-end; align-items: center; height: 100%; }}
.ff-nav-links a {{ color: {theme.MUTED}; text-decoration: none; font-weight: 500; font-size: .92rem; }}
.ff-nav-links a:hover {{ color: {theme.ACCENT}; }}
.ff-hero {{
    position: relative; overflow: hidden; text-align: center; border-radius: 32px; margin: 1.2rem 0 1rem 0;
    padding: 4.2rem 1.5rem 2.6rem 1.5rem; border: 1px solid rgba(90,82,74,.6);
    background:
      radial-gradient(700px 320px at 15% 0%, rgba(240,147,58,.20), transparent 70%),
      radial-gradient(600px 300px at 90% 100%, rgba(201,183,156,.16), transparent 70%),
      linear-gradient(160deg, {theme.SURFACE_RAISED}, {theme.BG});
    box-shadow: 10px 14px 30px rgba(0,0,0,.4), -6px -6px 16px rgba(255,240,220,.03);
}}
/* faint woven threads: two crossing sets of fine lines */
.ff-hero::before {{
    content: ""; position: absolute; inset: 0; pointer-events: none; opacity: .5;
    background:
      repeating-linear-gradient(0deg, rgba(243,237,228,.045) 0 2px, transparent 2px 18px),
      repeating-linear-gradient(90deg, rgba(240,147,58,.05) 0 2px, transparent 2px 18px);
    mask-image: radial-gradient(ellipse at center, black 30%, transparent 75%);
    -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 75%);
}}
.ff-hero > * {{ position: relative; }}
.ff-hero-title {{
    font-size: clamp(2.6rem, 8vw, 5.2rem); font-weight: 800; letter-spacing: .16em; line-height: 1; margin: 0;
    background: linear-gradient(180deg, #FFF8EE 10%, {theme.ACCENT_SOFT} 95%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.ff-hero-sub {{ color: {theme.ACCENT}; font-weight: 600; letter-spacing: .32em; text-transform: uppercase;
                font-size: clamp(.78rem, 2.2vw, 1rem); margin: 1rem 0 .9rem 0; }}
.ff-hero-tag {{ color: {theme.MUTED}; font-size: clamp(.95rem, 2.4vw, 1.12rem); max-width: 620px;
                margin: 0 auto !important; text-align: center; }}
.ff-motto {{ text-align: center; font-size: 1.15rem; font-weight: 600; color: {theme.TEXT}; margin: 2.4rem 0 .4rem 0; }}
.ff-motto span {{ color: {theme.ACCENT}; }}
.ff-footer-line {{ text-align: center; color: {theme.MUTED}; font-size: .8rem; padding: 1.4rem 0 .5rem 0;
                   border-top: 1px solid {theme.BORDER}; margin-top: 1.6rem; }}
@media (max-width: 640px) {{
    .ff-nav-links {{ justify-content: flex-start; gap: 1rem; }}
    .ff-hero {{ padding: 2.6rem 1rem 1.8rem 1rem; }}
    .ff-hero-title {{ font-size: 2.1rem; letter-spacing: .08em; }}
    .ff-hero-sub {{ letter-spacing: .18em; }}
}}
</style>
"""

st.markdown(HERO_CSS, unsafe_allow_html=True)
st.markdown('<div id="top"></div>', unsafe_allow_html=True)

# ---------- top bar ----------
brand, links, sign_in, sign_up = st.columns([3, 3.4, 1.1, 1.1], vertical_alignment="center")
brand.markdown(theme.brand_title(), unsafe_allow_html=True)
links.markdown('<div class="ff-nav-links"><a href="#top">Home</a><a href="#features">Features</a>'
               '<a href="#how-it-works">How it works</a></div>', unsafe_allow_html=True)
if sign_in.button("Sign In", key="home_top_signin", width="stretch"):
    st.switch_page("views/sign_in.py")
if sign_up.button("Sign Up", key="home_top_signup", type="primary", width="stretch"):
    st.switch_page("views/sign_up.py")

notice = auth_ui.pop_notice()
if notice:
    st.info(notice)

# ---------- hero ----------
st.markdown(
    '<div class="ff-hero"><h1 class="ff-hero-title">FABRICFLOW</h1>'
    '<div class="ff-hero-sub">Textile Multi Agent AI</div>'
    '<p class="ff-hero-tag">Predict production delays early and get explainable, human-approved corrective actions.</p>'
    "</div>",
    unsafe_allow_html=True,
)
_, hero_in, hero_up, _ = st.columns([1.6, 1, 1, 1.6])
if hero_in.button("Sign In", key="home_hero_signin", width="stretch"):
    st.switch_page("views/sign_in.py")
if hero_up.button("Sign Up", key="home_hero_signup", type="primary", width="stretch"):
    st.switch_page("views/sign_up.py")

# ---------- the four agents ----------
st.markdown(theme.section_title("The four agents", anchor="features"), unsafe_allow_html=True)
agents = [
    ("order", "Order Analysis Agent", "Reads customer messages and PDF purchase orders and extracts product, quantity, priority and deadline."),
    ("factory", "Resource & Production Agent", "Checks machine capacity, material stock and supplier lead times for every order."),
    ("clock", "Delay Prediction Agent", "A Random Forest model estimates the delay probability and explains the main risk factors."),
    ("bulb", "Recommendation Agent", "Finds matching SOPs in the knowledge base and proposes corrective actions with sources."),
]
for column, (icon, title, text) in zip(st.columns(4), agents):
    column.markdown(theme.feature_card(icon, title, text), unsafe_allow_html=True)

# ---------- how it works ----------
st.markdown(theme.section_title("How it works", anchor="how-it-works"), unsafe_allow_html=True)
st.markdown(theme.flow_steps(["Customer Order", "Order Analysis", "Resource & Production",
                              "Delay Prediction", "Recommendation", "Manager Review"]), unsafe_allow_html=True)

# ---------- categories & information ----------
st.markdown(theme.section_title("Categories & information"), unsafe_allow_html=True)
tiles = [("order", "Order Management"), ("factory", "Resource Check"), ("alert", "Delay Risk"),
         ("bulb", "Recommendations"), ("book", "Knowledge Base"), ("user_check", "Human Approval")]
for column, (icon, label) in zip(st.columns(6), tiles):
    column.markdown(theme.info_tile(icon, label), unsafe_allow_html=True)

st.markdown('<div class="ff-motto">AI recommends. <span>The manager decides.</span></div>', unsafe_allow_html=True)
st.markdown('<div class="ff-footer-line">© FabricFlow · Textile Multi Agent AI · '
            'Order Analysis · Resource & Production · Delay Prediction · Recommendation</div>',
            unsafe_allow_html=True)
