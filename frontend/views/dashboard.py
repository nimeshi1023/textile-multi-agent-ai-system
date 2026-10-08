"""Manager Dashboard (signed in). All data comes from the backend API."""
from datetime import date, timedelta

import httpx
import pandas as pd
import streamlit as st

import auth_ui
import theme

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:   # requirements.txt: plotly
    HAS_PLOTLY = False

API_URL = auth_ui.API_URL


def api_get(path: str, params: dict = None, timeout: float = 30.0):
    """GET with the sign-in token. 401 -> back to Sign In; backend down -> error card."""
    try:
        response = httpx.get(f"{API_URL}{path}", params=params, headers=auth_headers(), timeout=timeout)
    except httpx.HTTPError:
        st.error(f"The FabricFlow backend is not reachable at {API_URL}. Start it and refresh this page.")
        st.stop()
    if response.status_code == 401:
        auth_ui.clear_session("Your session has expired. Please sign in again.", goto_sign_in=True)
        st.rerun()
    response.raise_for_status()
    return response.json()


def auth_headers() -> dict:
    return auth_ui.auth_headers()


def chart_card(title: str, key: str):
    box = st.container(key=f"ffcard_{key}")
    box.markdown(theme.card_title(title), unsafe_allow_html=True)
    return box


def show_figure(box, fig, height: int = 290) -> None:
    box.plotly_chart(theme.style_figure(fig, height), config=theme.PLOTLY_CONFIG, width="stretch")


def bar_chart(box, labels, values, horizontal=False, color=theme.ACCENT, percent=False, height=290) -> None:
    if not labels:
        box.markdown(theme.empty_state(), unsafe_allow_html=True)
        return
    if not HAS_PLOTLY:
        box.bar_chart(pd.DataFrame({"value": values}, index=labels), horizontal=horizontal)
        return
    text = [f"{v:.0%}" if percent else f"{v:,}" for v in values]
    headroom = [0, max(values) * 1.18]   # room for the value labels outside the bars
    if horizontal:
        fig = go.Figure(go.Bar(x=values[::-1], y=labels[::-1], orientation="h", marker_color=color,
                               text=text[::-1], textposition="outside", cliponaxis=False,
                               marker=dict(cornerradius=8), hovertemplate="%{y}: %{text}<extra></extra>"))
        fig.update_xaxes(range=headroom, tickformat=".0%" if percent else None)
    else:
        fig = go.Figure(go.Bar(x=labels, y=values, marker_color=color, text=text, textposition="outside",
                               cliponaxis=False, marker=dict(cornerradius=8),
                               hovertemplate="%{x}: %{text}<extra></extra>"))
        fig.update_yaxes(range=headroom, tickformat=".0%" if percent else None)
    fig.update_layout(showlegend=False)
    show_figure(box, fig, height)


def donut_chart(box, labels, values, colors=None, center="", height=290) -> None:
    if not labels or sum(values) == 0:
        box.markdown(theme.empty_state(), unsafe_allow_html=True)
        return
    if not HAS_PLOTLY:
        box.bar_chart(pd.DataFrame({"count": values}, index=labels))
        return
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.64, sort=False,
                           marker=dict(colors=colors, line=dict(color=theme.SURFACE, width=3)),
                           textinfo="value", textfont=dict(color="#2A211A", size=13)))
    fig.update_layout(annotations=[dict(text=center, showarrow=False, font=dict(size=20, color=theme.TEXT))])
    show_figure(box, fig, height)


manager = st.session_state.get(auth_ui.MANAGER_KEY) or {}
summary = api_get("/dashboard/summary")
orders = api_get("/orders")

# ---------- header ----------
st.markdown(f"## Welcome back, {manager.get('manager_id', '')}")
st.markdown(f'<div class="ff-muted">{manager.get("manager_type", "")} · {date.today():%A, %d %B %Y}</div>',
            unsafe_allow_html=True)

# ---------- 1. KPI cards ----------
st.markdown(theme.section_title("Overview"), unsafe_allow_html=True)
kpis = [
    ("Total Orders", summary["total_orders"], "in the order book", "order"),
    ("Due in 7 Days", summary["orders_due_within_7_days"], "deadlines this week", "calendar"),
    ("High-Priority", summary["high_priority_orders"], "orders marked High", "flag"),
    ("Decisions Made", summary["decisions_total"], "approved / rejected", "user_check"),
]
for column, (label, value, hint, icon) in zip(st.columns(4), kpis):
    column.markdown(theme.kpi_card(label, value, hint, icon), unsafe_allow_html=True)

# ---------- 2. orders over time + priority ----------
st.markdown(theme.section_title("Orders"), unsafe_allow_html=True)
left, right = st.columns([1.6, 1])
per_day ={row["date"]: row["count"] for row in summary["orders_per_day"]}
days = [date.today() - timedelta(days=i) for i in range(29, -1, -1)]
with left:
    box = chart_card("Orders over time · last 30 days", "over_time")
    if not per_day:
        box.markdown(theme.empty_state(), unsafe_allow_html=True)
    elif HAS_PLOTLY:
        counts = [per_day.get(str(d), 0) for d in days]
        fig = go.Figure(go.Scatter(x=days, y=counts, mode="lines+markers", line=dict(color=theme.ACCENT, width=3),
                                   fill="tozeroy", fillcolor="rgba(240,147,58,0.18)", marker=dict(size=6),
                                   name="Orders"))
        fig.update_layout(showlegend=False)
        fig.update_yaxes(rangemode="tozero", dtick=1)
        show_figure(box, fig)
    else:
        box.line_chart(pd.DataFrame({"orders": [per_day.get(str(d), 0) for d in days]}, index=days))
with right:
    box = chart_card("Orders by priority", "priority")
    rows = summary["orders_by_priority"]
    donut_chart(box, [r["label"] for r in rows], [r["count"] for r in rows],
                colors=[theme.PRIORITY_COLORS.get(r["label"], theme.ACCENT_SOFT) for r in rows],
                center=str(summary["total_orders"]))

# ---------- 3. product type + historical delay rate ----------
left, right = st.columns(2)
with left:
    box = chart_card("Orders by product type", "product")
    rows = summary["orders_by_product_type"]
    bar_chart(box, [r["label"] for r in rows], [r["count"] for r in rows], horizontal=True)
with right:
    box = chart_card("Historical delay rate by product · 3,000 past orders", "delay_rate")
    rows = summary["historical_delay_rate_by_product"]
    bar_chart(box, [r["label"] for r in rows], [r["rate"] for r in rows], color=theme.ACCENT_SOFT, percent=True)

# ---------- 4. delay reasons + decisions ----------
st.markdown(theme.section_title("Risk & decisions"), unsafe_allow_html=True)
left, right = st.columns([1.6, 1])
with left:
    box = chart_card("Top delay reasons · historical orders", "reasons")
    rows = summary["top_delay_reasons"]
    bar_chart(box, [r["label"] for r in rows], [r["count"] for r in rows], horizontal=True, color=theme.ACCENT_SOFT)
with right:
    box = chart_card("Manager decisions", "decisions")
    rows = summary["decisions_by_type"]
    decision_colors = {"approved": theme.SUCCESS, "rejected": theme.DANGER, "overridden": theme.WARNING}
    donut_chart(box, [r["label"].title() for r in rows], [r["count"] for r in rows],
                colors=[decision_colors.get(r["label"], theme.ACCENT_SOFT) for r in rows],
                center=str(summary["decisions_total"]))

# ---------- 5. risk overview (on demand) ----------
st.markdown(theme.section_title("Risk overview · latest orders"), unsafe_allow_html=True)
box = st.container(key="ffcard_risk")
load_col, refresh_col, _ = box.columns([1.3, 1, 3])
if load_col.button("Load risk overview", type="primary", key="load_risk", width="stretch"):
    with st.spinner("Running the Resource and Delay Risk agents for the latest orders..."):
        try:
            st.session_state["ff_risk_overview"] = api_get("/dashboard/risk-overview", timeout=180)
        except httpx.HTTPStatusError as e:
            box.error(f"Risk overview unavailable: {e.response.text}")
if "ff_risk_overview" in st.session_state and refresh_col.button("Refresh", key="refresh_risk", width="stretch"):
    with st.spinner("Recomputing..."):
        st.session_state["ff_risk_overview"] = api_get("/dashboard/risk-overview", params={"refresh": "true"}, timeout=180)

risk = st.session_state.get("ff_risk_overview")
if risk:
    chart_col, table_col = box.columns([1, 1.8])
    levels = [lvl for lvl in ("Low", "Medium", "High", "Unavailable") if risk["counts"].get(lvl)]
    donut_chart(chart_col, levels, [risk["counts"][lvl] for lvl in levels],
                colors=[theme.RISK_COLORS[lvl] for lvl in levels], center=str(len(risk["orders"])), height=260)
    table = pd.DataFrame([{
        "Order": o["order_id"], "Product": o["product_type"], "Priority": o["priority"],
        "Deadline": o["deadline_date"], "Risk": o["risk_level"],
        "Delay %": o["delay_probability_pct"], "Drivers": ", ".join(o["risk_drivers"]) or o.get("error", "")[:60],
    } for o in risk["orders"]])
    table_col.dataframe(table, hide_index=True, width="stretch", height=280)
    box.caption(f"Computed {risk['computed_at']}{' (cached)' if risk.get('cached') else ''} · "
                "probabilities come only from the Delay Risk model")
else:
    box.markdown(theme.empty_state("Press “Load risk overview” to assess the latest orders "
                                   "(runs the Resource and Delay Risk agents, no LLM)."), unsafe_allow_html=True)

# ---------- 6. upcoming deadlines + recent orders ----------
st.markdown(theme.section_title("Deadlines & recent orders"), unsafe_allow_html=True)
left, right = st.columns(2)
with left:
    box = chart_card("Upcoming deadlines · next 14 days", "deadlines")
    rows = summary["deadlines_next_14_days"]
    if not rows:
        box.markdown(theme.empty_state("No deadlines in the next 14 days"), unsafe_allow_html=True)
    else:
        lines = "".join(
            f"<tr><td><b>{r['order_id']}</b></td><td>{r['product_type']}</td><td>{r['quantity']:,}</td>"
            f"<td>{theme.priority_badge(r['priority'])}</td><td>{r['deadline_date']}</td>"
            f"<td>{r['days_left']} d</td></tr>" for r in rows)
        box.markdown(
            "<style>.ff-table td, .ff-table th{white-space:nowrap;padding:.45rem .55rem;"
            f"border-bottom:1px solid {theme.BORDER}}}.ff-table th{{color:{theme.MUTED};text-align:left;"
            "font-weight:600}</style>"
            "<div style='overflow-x:auto'><table class='ff-table' style='width:100%;border-collapse:collapse;"
            "font-size:.86rem'><tr><th>Order</th><th>Product</th><th>Qty</th><th>Priority</th>"
            f"<th>Deadline</th><th>Left</th></tr>{lines}</table></div>",
            unsafe_allow_html=True)
with right:
    box = chart_card("Recent orders", "recent")
    if not orders:
        box.markdown(theme.empty_state("No orders yet"), unsafe_allow_html=True)
    else:
        recent = pd.DataFrame(orders).sort_values(["order_date", "cus_ord_id"], ascending=False).head(8)
        recent = recent[["cus_ord_id", "product_type", "quantity", "priority", "deadline_date"]].rename(columns={
            "cus_ord_id": "Order", "product_type": "Product", "quantity": "Qty",
            "priority": "Priority", "deadline_date": "Deadline"})
        box.dataframe(recent, hide_index=True, width="stretch")

# ---------- 7. quick actions ----------
st.markdown(theme.section_title("Quick actions"), unsafe_allow_html=True)
for column, (label, target, kind) in zip(st.columns(3), [
        ("New Order", "pages/new_order.py", "primary"),
        ("Delay Prediction", "pages/delay_prediction.py", "secondary"),
        ("Recommendations", "pages/recommendation.py", "secondary")]):
    if column.button(label, key=f"quick_{label}", type=kind, width="stretch"):
        st.switch_page(target)
