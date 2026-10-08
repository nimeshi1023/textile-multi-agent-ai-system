import altair as alt
import httpx
import pandas as pd
import streamlit as st

from auth_ui import auth_headers, render_user_sidebar, require_login

require_login()
render_user_sidebar()

API_URL = "http://localhost:8000"
TRAIN_COMMAND = "cd backend && python -m app.ml.train"
BACKEND_COMMAND = "cd backend && uvicorn app.main:app --reload --port 8000"
RISK_COLORS = {"Low": "#2e7d32", "Medium": "#ef6c00", "High": "#c62828"}

st.title("Delay Prediction")


def api_get(path: str):
    response = httpx.get(f"{API_URL}{path}", headers=auth_headers(), timeout=30.0)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict, timeout=60.0):
    response = httpx.post(f"{API_URL}{path}", json=payload, headers=auth_headers(), timeout=timeout)
    response.raise_for_status()
    return response.json()


def error_detail(e: httpx.HTTPStatusError) -> str:
    try:
        return str(e.response.json().get("detail", e.response.text))
    except ValueError:
        return e.response.text


def backend_down():
    st.error(f"Backend is not reachable at {API_URL}. Start it with:")
    st.code(BACKEND_COMMAND)
    st.stop()


def tag(label: str, color: str) -> str:
    return (f"<span style='background:{color};color:white;padding:4px 10px;border-radius:12px;"
            f"margin-right:6px;font-size:0.85em;font-weight:600'>{label}</span>")


# ---------- 1. Select an order ----------
try:
    orders = api_get("/orders")
except httpx.ConnectError:
    backend_down()
except httpx.HTTPStatusError as e:
    st.error(f"Could not load orders: {error_detail(e)}")
    st.stop()

if not orders:
    st.info("No orders yet. Create one on the New Order page first.")
    st.stop()

orders = sorted(orders, key=lambda o: o["cus_ord_id"], reverse=True)   # latest first
selected = st.selectbox(
    "Order",
    orders,
    format_func=lambda o: (f"{o['cus_ord_id']}  |  {o['product_type']}  |  "
                           f"{o['quantity']:,} units  |  deadline {o['deadline_date']}"),
)

# ---------- 2. Resource Agent -> Delay Risk Agent ----------
if st.button("Run Delay Prediction", type="primary"):
    st.session_state.pop("delay_result", None)
    order_id = selected["cus_ord_id"]

    with st.spinner("Resource & Production Agent: checking machines, material and suppliers..."):
        try:
            resource = api_post("/production/analyze", {"order_id": order_id}, timeout=None)
        except httpx.ConnectError:
            backend_down()
        except httpx.HTTPStatusError as e:
            st.error(f"Resource Agent failed: {error_detail(e)}")
            st.stop()

    with st.spinner("Delay Risk Agent: predicting delay probability..."):
        try:
            risk = api_post("/risk/predict", {"order_id": order_id, "resource_result": resource})
            st.session_state.delay_result = {"resource": resource, "risk": risk}
        except httpx.ConnectError:
            backend_down()
        except httpx.HTTPStatusError as e:
            st.session_state.delay_result = {"resource": resource, "risk": None}
            code, detail = e.response.status_code, error_detail(e)
            if code == 503:
                st.error("The delay prediction model is not trained yet. Train it with:")
                st.code(TRAIN_COMMAND)
            elif code == 404:
                st.error(f"Unknown order: {detail}")
            elif code == 422:
                st.warning(f"Cannot predict this order: {detail}")
            else:
                st.error(f"Delay Risk Agent failed ({code}): {detail}")

# ---------- 3. Results ----------
result = st.session_state.get("delay_result")
if result:
    resource, risk = result["resource"], result["risk"]

    st.subheader("Resource summary")
    calcs = resource.get("calculations") or {}
    machine = resource.get("machine") or {}
    c1, c2, c3 = st.columns(3)
    c1.metric("Resource status", resource.get("resource_status", "-"))
    if calcs:
        c2.metric("Production days needed", f"{calcs['required_production_days']:.1f}",
                  help=f"Days remaining: {calcs['days_remaining']}")
        c3.metric("Available capacity / day", f"{calcs['available_capacity_per_day']:,.0f}")
        st.caption(
            f"Days remaining: {calcs['days_remaining']}  |  Machine: {machine.get('machine_id', '-')} "
            f"({machine.get('status', '-')})  |  Material required: {calcs['material_required']:,.1f}  |  "
            f"Material left after order: {calcs['material_available']:,.1f}"
        )
    if resource.get("issues"):
        st.markdown(" ".join(tag(i, "#616161") for i in resource["issues"]), unsafe_allow_html=True)

    if risk:
        st.subheader("Delay risk")
        level = risk["risk_level"]
        c1, c2 = st.columns([1, 1])
        c1.metric("Delay probability", f"{risk['delay_probability_pct']:.1f}%")
        c2.markdown(
            f"<div style='margin-top:1.6rem'>{tag(level.upper() + ' RISK', RISK_COLORS.get(level, '#616161'))}</div>",
            unsafe_allow_html=True,
        )
        st.progress(min(max(risk["delay_probability"], 0.0), 1.0))
        t = risk["thresholds"]
        st.caption(f"Low ≤ {t['low_max']:.0%} < Medium ≤ {t['medium_max']:.0%} < High")

        if risk["risk_drivers"]:
            st.markdown("**Risk drivers**")
            st.markdown(" ".join(tag(d, "#c62828") for d in risk["risk_drivers"]), unsafe_allow_html=True)

        st.markdown("**Top factors for this prediction**")
        factors = pd.DataFrame(risk["top_factors"])
        if not factors.empty:
            factors["value"] = factors["value"].astype(str)
            factors["impact_pct"] = factors["impact"] * 100
            chart = (
                alt.Chart(factors)
                .mark_bar()
                .encode(
                    x=alt.X("impact_pct:Q", title="Share of impact (%)"),
                    y=alt.Y("feature:N", sort="-x", title=None),
                    color=alt.Color(
                        "direction:N",
                        scale=alt.Scale(domain=["increases risk", "reduces risk"],
                                        range=["#c62828", "#2e7d32"]),
                        legend=alt.Legend(title=None, orient="bottom"),
                    ),
                    tooltip=["feature", "value", "direction", alt.Tooltip("impact_pct:Q", format=".1f")],
                )
            )
            st.altair_chart(chart, width="stretch")

        st.markdown("**Explanation**")
        st.info(risk["explanation"])
        st.caption(f"Explanation source: {risk['explanation_source']}  |  "
                   f"Probability source: {risk['model']['name']} (ML model only)")
        if risk["missing_features"]:
            st.caption("Filled with safe defaults: " + ", ".join(risk["missing_features"]))
