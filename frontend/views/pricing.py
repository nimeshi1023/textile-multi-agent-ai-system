"""Pricing page: commercial plans, plan comparison, savings estimate and FAQ (no sign-in needed)."""
import html

import streamlit as st

import auth_ui
import theme

ANNUAL_DISCOUNT = 0.20  # annual billing: 20% off the monthly price

# monthly price in USD (None = custom quote)
PLANS = [
    {
        "name": "Starter", "price": 49, "tagline": "For a single workshop getting started with delay risk.",
        "features": ["1 factory site", "Up to 200 orders / month", "Order Analysis Agent",
                     "Delay Prediction Agent", "2 manager seats", "Email support"],
        "cta": "Start free trial",
    },
    {
        "name": "Professional", "price": 199, "popular": True,
        "tagline": "All four agents for mills running daily production.",
        "features": ["Up to 3 factory sites", "Up to 2,000 orders / month", "All four AI agents",
                     "SOP-backed recommendations with sources", "PDF purchase order parsing",
                     "10 manager seats", "Priority support"],
        "cta": "Start free trial",
    },
    {
        "name": "Enterprise", "price": None, "tagline": "For groups with many plants and their own data rules.",
        "features": ["Unlimited sites and orders", "Model retrained on your history",
                     "Private LLM / on-premise deployment", "Custom knowledge base onboarding",
                     "SSO and audit logs", "Unlimited seats", "Dedicated manager & 99.9% SLA"],
        "cta": "Contact sales",
    },
]

# feature -> value per plan (True/False or text), same order as PLANS
COMPARISON = [
    ("Orders per month", "200", "2,000", "Unlimited"),
    ("Factory sites", "1", "3", "Unlimited"),
    ("Manager seats", "2", "10", "Unlimited"),
    ("Order Analysis Agent", True, True, True),
    ("Resource & Production Agent", False, True, True),
    ("Delay Prediction Agent", True, True, True),
    ("Recommendation Agent (SOP search)", False, True, True),
    ("PDF purchase order parsing", False, True, True),
    ("Explainable risk factors", True, True, True),
    ("Model retraining on your data", False, False, True),
    ("On-premise / private LLM", False, False, True),
    ("SSO and audit logs", False, False, True),
    ("Support", "Email", "Priority", "Dedicated + SLA"),
]

FAQ = [
    ("Is there a free trial?",
     "Yes. Starter and Professional include a 14-day free trial with all plan features. No card is needed to start."),
    ("Can I change plans later?",
     "Yes. You can upgrade or downgrade at any time; the change is prorated on your next invoice."),
    ("What counts as an order?",
     "Each customer order analysed by FabricFlow counts once, however many times you re-run predictions on it."),
    ("Who makes the final decision?",
     "Always your manager. FabricFlow predicts and recommends; every corrective action needs human approval."),
    ("Where is our data stored?",
     "Cloud plans use encrypted storage. Enterprise can run fully on your own servers with a private language model."),
]

PRICING_CSS = f"""
<style>
.ff-nav-links {{ display: flex; gap: 1.4rem; justify-content: flex-end; align-items: center; height: 100%; }}
.ff-nav-links a {{ color: {theme.MUTED}; text-decoration: none; font-weight: 500; font-size: .92rem; }}
.ff-nav-links a:hover, .ff-nav-links a.active {{ color: {theme.ACCENT}; }}
.ff-price-head {{ text-align: center; margin: 1.4rem 0 1.2rem 0; }}
.ff-price-head h1 {{ font-size: clamp(1.8rem, 5vw, 2.8rem); font-weight: 800; margin: 0 0 .5rem 0; }}
.ff-price-head h1 span {{ color: {theme.ACCENT}; }}
.ff-price-head p {{ color: {theme.MUTED}; max-width: 620px; margin: 0 auto; }}
.st-key-ff_billing {{ display: flex; justify-content: center; }}
.st-key-ff_billing > div {{ width: auto !important; }}
.ff-plan {{ position: relative; display: flex; flex-direction: column; min-height: 470px; padding: 1.6rem 1.5rem; }}
.ff-plan.popular {{ border: 1.5px solid {theme.ACCENT};
                    box-shadow: 0 10px 30px rgba(240,147,58,.22), -5px -5px 14px rgba(255,240,220,.035); }}
.ff-plan-ribbon {{ position: absolute; top: -12px; left: 50%; transform: translateX(-50%); white-space: nowrap;
                   background: {theme.ACCENT}; color: #2A211A; font-size: .72rem; font-weight: 800;
                   letter-spacing: .1em; text-transform: uppercase; padding: .25rem .8rem; border-radius: 999px; }}
.ff-plan-name {{ font-weight: 800; font-size: 1.2rem; color: {theme.TEXT}; }}
.ff-plan-tag {{ color: {theme.MUTED}; font-size: .88rem; line-height: 1.45; margin: .3rem 0 1rem 0; min-height: 2.6em; }}
.ff-plan-price {{ font-size: 2.6rem; font-weight: 800; color: {theme.TEXT}; line-height: 1; }}
.ff-plan-price small {{ font-size: .9rem; font-weight: 500; color: {theme.MUTED}; }}
.ff-plan-note {{ color: {theme.ACCENT_SOFT}; font-size: .8rem; min-height: 1.3em; margin: .45rem 0 1rem 0; }}
.ff-plan ul {{ list-style: none; padding: 0; margin: 0; border-top: 1px solid {theme.BORDER}; padding-top: 1rem; }}
.ff-plan li {{ display: flex; gap: .55rem; align-items: flex-start; color: {theme.TEXT}; font-size: .9rem;
               margin-bottom: .55rem; }}
.ff-plan li svg {{ width: 18px; height: 18px; color: {theme.ACCENT}; flex: none; margin-top: .1rem; }}
.ff-compare {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
.ff-compare th, .ff-compare td {{ padding: .7rem .8rem; border-bottom: 1px solid {theme.BORDER}; text-align: center; }}
.ff-compare th {{ color: {theme.MUTED}; text-transform: uppercase; letter-spacing: .1em; font-size: .74rem; }}
.ff-compare th.hl {{ color: {theme.ACCENT}; }}
.ff-compare td:first-child, .ff-compare th:first-child {{ text-align: left; color: {theme.TEXT}; }}
.ff-compare td.hl {{ background: rgba(240,147,58,.06); }}
.ff-yes {{ color: {theme.SUCCESS}; font-weight: 800; }}
.ff-no {{ color: {theme.BORDER}; }}
.ff-compare-wrap {{ overflow-x: auto; }}
.ff-saving {{ font-size: 2.2rem; font-weight: 800; color: {theme.SUCCESS}; line-height: 1.1; }}
.ff-footer-line {{ text-align: center; color: {theme.MUTED}; font-size: .8rem; padding: 1.4rem 0 .5rem 0;
                   border-top: 1px solid {theme.BORDER}; margin-top: 1.6rem; }}
@media (max-width: 640px) {{
    .ff-nav-links {{ justify-content: flex-start; gap: 1rem; }}
    .ff-plan {{ min-height: 0; }}
}}
</style>
"""

signed_in = bool(st.session_state.get(auth_ui.TOKEN_KEY))


def _price_html(plan: dict, annual: bool) -> tuple:
    if plan["price"] is None:
        return "Custom", "Volume pricing for your group"
    if annual:
        monthly = round(plan["price"] * (1 - ANNUAL_DISCOUNT))
        return (f"${monthly}<small> / month</small>",
                f"${monthly * 12:,} billed yearly · save ${(plan['price'] - monthly) * 12:,}")
    return f"${plan['price']}<small> / month</small>", "Billed monthly · cancel anytime"


def _plan_card(plan: dict, annual: bool) -> str:
    price, note = _price_html(plan, annual)
    popular = plan.get("popular", False)
    items = "".join(f"<li>{theme.ICONS['check']}<span>{html.escape(f)}</span></li>" for f in plan["features"])
    ribbon = '<div class="ff-plan-ribbon">Most popular</div>' if popular else ""
    return (f'<div class="ff-card ff-plan{" popular" if popular else ""}">{ribbon}'
            f'<div class="ff-plan-name">{html.escape(plan["name"])}</div>'
            f'<div class="ff-plan-tag">{html.escape(plan["tagline"])}</div>'
            f'<div class="ff-plan-price">{price}</div><div class="ff-plan-note">{html.escape(note)}</div>'
            f"<ul>{items}</ul></div>")


def _cell(value, highlight: bool) -> str:
    cls = ' class="hl"' if highlight else ""
    if value is True:
        return f'<td{cls}><span class="ff-yes">✓</span></td>'
    if value is False:
        return f'<td{cls}><span class="ff-no">—</span></td>'
    return f"<td{cls}>{html.escape(str(value))}</td>"


def _comparison_table() -> str:
    popular_col = next(i for i, p in enumerate(PLANS) if p.get("popular"))
    head = "".join(f'<th{" class=hl" if i == popular_col else ""}>{html.escape(p["name"])}</th>'
                   for i, p in enumerate(PLANS))
    rows = "".join(
        f"<tr><td>{html.escape(feature)}</td>" + "".join(_cell(v, i == popular_col) for i, v in enumerate(values))
        + "</tr>"
        for feature, *values in COMPARISON
    )
    return (f'<div class="ff-card ff-compare-wrap"><table class="ff-compare">'
            f"<thead><tr><th>Feature</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>")


def _on_plan_click(plan: dict) -> None:
    if plan["price"] is None:
        st.session_state["ff_pricing_notice"] = ("Thanks for your interest in Enterprise. "
                                                 "Email sales@fabricflow.ai and our team will prepare a quote.")
    elif signed_in:
        st.session_state["ff_pricing_notice"] = (f"Your {plan['name']} trial request was noted. "
                                                 "An administrator will enable it on your account.")
    else:
        st.switch_page("views/sign_up.py")


st.markdown(PRICING_CSS, unsafe_allow_html=True)

# ---------- top bar (signed out only; the signed-in shell draws its own) ----------
if not signed_in:
    brand, links, sign_in, sign_up = st.columns([3, 3.4, 1.1, 1.1], vertical_alignment="center")
    brand.markdown(theme.brand_title(), unsafe_allow_html=True)
    links.markdown('<div class="ff-nav-links"><a href="home" target="_self">Home</a>'
                   '<a href="home#features" target="_self">Features</a>'
                   '<a class="active" href="pricing" target="_self">Pricing</a></div>', unsafe_allow_html=True)
    if sign_in.button("Sign In", key="pricing_top_signin", width="stretch"):
        st.switch_page("views/sign_in.py")
    if sign_up.button("Sign Up", key="pricing_top_signup", type="primary", width="stretch"):
        st.switch_page("views/sign_up.py")

# ---------- header + billing toggle ----------
st.markdown('<div class="ff-price-head"><h1>Simple pricing for <span>on-time</span> production</h1>'
            "<p>Start with a 14-day free trial. Pick the plan that matches your order volume "
            "and upgrade as your factory grows.</p></div>", unsafe_allow_html=True)

with st.container(key="ff_billing"):
    billing = st.segmented_control("Billing", ["Monthly", f"Yearly (save {ANNUAL_DISCOUNT:.0%})"],
                                   default="Monthly", key="ff_billing_choice", label_visibility="collapsed")
annual = bool(billing) and billing.startswith("Yearly")

notice = st.session_state.pop("ff_pricing_notice", None)
if notice:
    st.success(notice)

# ---------- plan cards ----------
st.write("")
for column, plan in zip(st.columns(len(PLANS), gap="medium"), PLANS):
    with column:
        st.markdown(_plan_card(plan, annual), unsafe_allow_html=True)
        st.write("")
        if st.button(plan["cta"], key=f"pricing_cta_{plan['name']}", width="stretch",
                     type="primary" if plan.get("popular") else "secondary"):
            _on_plan_click(plan)
            st.rerun()

# ---------- comparison ----------
st.markdown(theme.section_title("Compare plans"), unsafe_allow_html=True)
st.markdown(_comparison_table(), unsafe_allow_html=True)

# ---------- savings estimate ----------
st.markdown(theme.section_title("Estimate your savings"), unsafe_allow_html=True)
with st.container(key="ffcard_savings"):
    inputs, result = st.columns([1.3, 1], gap="large")
    with inputs:
        orders = st.slider("Orders per month", 20, 3000, 300, step=10)
        order_value = st.number_input("Average order value (USD)", min_value=100, value=5000, step=500)
        late_rate = st.slider("Orders delivered late today (%)", 0, 60, 15)
        penalty = st.slider("Cost of a late order (% of order value)", 0, 30, 8,
                            help="Penalties, air freight, discounts and lost repeat business.")
        reduction = st.slider("Late orders prevented by early warning (%)", 0, 80, 30,
                              help="An assumption for this estimate, not a guarantee.")
    late_cost = orders * order_value * late_rate / 100 * penalty / 100
    saving = late_cost * reduction / 100
    plan = PLANS[0] if orders <= 200 else PLANS[1] if orders <= 2000 else PLANS[2]
    plan_cost = None if plan["price"] is None else plan["price"] * (1 - ANNUAL_DISCOUNT if annual else 1)
    with result:
        st.markdown(theme.card_title("Estimated monthly saving"), unsafe_allow_html=True)
        st.markdown(f'<div class="ff-saving">${saving:,.0f}</div>', unsafe_allow_html=True)
        st.caption(f"Current cost of late orders: ${late_cost:,.0f} / month")
        st.markdown(f"Suggested plan: **{plan['name']}**")
        if plan_cost is not None:
            st.markdown(f"Plan cost: **${plan_cost:,.0f} / month**")
            if plan_cost > 0 and saving > 0:
                st.markdown(f"Return on plan cost: **{saving / plan_cost:,.1f}×**")
        else:
            st.markdown("Plan cost: **custom quote**")
        st.caption("Illustrative estimate based on your inputs. Actual results depend on your data and processes.")

# ---------- FAQ ----------
st.markdown(theme.section_title("Frequently asked questions"), unsafe_allow_html=True)
for question, answer in FAQ:
    with st.expander(question):
        st.write(answer)

# ---------- closing CTA ----------
if not signed_in:
    st.write("")
    _, cta, _ = st.columns([1.6, 1.2, 1.6])
    if cta.button("Start your free trial", key="pricing_bottom_signup", type="primary", width="stretch"):
        st.switch_page("views/sign_up.py")

st.markdown('<div class="ff-footer-line">Prices in USD, excluding taxes. '
            "AI recommends. The manager decides.</div>", unsafe_allow_html=True)
