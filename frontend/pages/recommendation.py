# Import libraries for API communication, data handling, and UI development

import httpx
import pandas as pd
import streamlit as st

# Import authentication helpers
from auth_ui import auth_headers, render_user_sidebar, require_login

require_login()
render_user_sidebar()

API_URL = "http://localhost:8000"
BUILD_COMMAND = "cd backend && python -m app.ir.build_index"
TRAIN_COMMAND = "cd backend && python -m app.ml.train"
BACKEND_COMMAND = "cd backend && uvicorn app.main:app --reload --port 8000"
RISK_COLORS = {"Low": "#2e7d32", "Medium": "#ef6c00", "High": "#c62828"}

st.title("Recommendations")
st.info("AI recommends. The manager decides.")


def api_get(path: str):
    response = httpx.get(f"{API_URL}{path}", headers=auth_headers(), timeout=60.0)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict, timeout=120.0):
    response = httpx.post(f"{API_URL}{path}", json=payload, headers=auth_headers(), timeout=timeout)
    response.raise_for_status()
    return response.json()


def error_detail(e: httpx.HTTPStatusError) -> str:
    try:
        detail = e.response.json().get("detail", e.response.text)
    except ValueError:
        return e.response.text
    if isinstance(detail, list):   # FastAPI validation errors
        return "; ".join(str(d.get("msg", d)) for d in detail)
    return str(detail)


def show_http_error(e: httpx.HTTPStatusError, context: str):
    code, detail = e.response.status_code, error_detail(e)
    if code == 503:
        st.error(f"{context}: {detail}")
        st.code(BUILD_COMMAND if "build_index" in detail else TRAIN_COMMAND)
    elif code == 404:
        st.error(f"Unknown order: {detail}")
    elif code == 422:
        st.warning(f"{context}: {detail}")
    else:
        st.error(f"{context} failed ({code}): {detail}")


def backend_down():
    st.error(f"Backend is not reachable at {API_URL}. Start it with:")
    st.code(BACKEND_COMMAND)
    st.stop()


def tag(label: str, color: str) -> str:
    return (f"<span style='background:{color};color:white;padding:3px 9px;border-radius:12px;"
            f"margin-right:6px;font-size:0.8em;font-weight:600'>{label}</span>")


# ---------- select an order ----------
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
order_id = selected["cus_ord_id"]

if st.button("Generate Recommendations", type="primary"):
    st.session_state.pop("rec_result", None)
    with st.spinner("Resource Agent → Delay Risk Agent → knowledge-base search → recommendations..."):
        try:
            st.session_state.rec_result = api_post("/recommendation/generate", {"order_id": order_id}, timeout=None)
        except httpx.ConnectError:
            backend_down()
        except httpx.HTTPStatusError as e:
            show_http_error(e, "Could not generate recommendations")

result = st.session_state.get("rec_result")
if result and result["order_id"] != order_id:
    result = None   # a different order is selected

# ---------- results ----------
if result:
    level = result["risk_level"]
    c1, c2 = st.columns(2)
    c1.metric("Delay probability", f"{result['delay_probability_pct']:.1f}%")
    c2.markdown(f"<div style='margin-top:1.6rem'>{tag(level.upper() + ' RISK', RISK_COLORS.get(level, '#616161'))}</div>",
                unsafe_allow_html=True)
    if result["drivers"]:
        st.markdown("**Risk drivers** " + " ".join(tag(d, "#c62828") for d in result["drivers"]),
                    unsafe_allow_html=True)

    st.markdown("**Explanation**")
    st.write(result["explanation"])
    st.caption(f"Explanation source: {result['explanation_source']}  |  "
               f"Retrieval: {result['retrieval_backend'] or 'not needed'}")

    if result["status"] == "no_action_needed":
        st.success("No action needed. The order can proceed as planned.")
    elif result["status"] == "no_supported_actions":
        st.warning("No action could be backed by a knowledge-base SOP. Please review this order manually.")

    sop_text = {d["document_id"]: d for d in result["retrieved_documents"]}
    for action in result["actions"]:
        with st.container(border=True):
            st.markdown(f"#### {action['rank']}. {action['action']}")
            st.write(action["reason"])
            st.markdown(" ".join(tag(f"{s['document_id']} · {s['title']} ({s['score']:.2f})", "#455a64")
                                 for s in action["sources"]), unsafe_allow_html=True)
            with st.expander("Show the full SOP text"):
                for s in action["sources"]:
                    doc = sop_text.get(s["document_id"])
                    st.markdown(f"**{s['document_id']} – {s['title']}**"
                                + (f"  \n_{doc['category']} · {doc['source_file']}_" if doc else ""))
                    st.write(doc["text"] if doc else "(text not returned)")

            with st.form(key=f"decision_{order_id}_{action['rank']}"):
                decided_by = st.text_input("Manager name", key=f"by_{action['rank']}")
                comment = st.text_area("Comment (required for Override)", key=f"comment_{action['rank']}", height=68)
                b1, b2, b3 = st.columns(3)
                clicked = None
                if b1.form_submit_button("Approve"):
                    clicked = "approved"
                if b2.form_submit_button("Reject"):
                    clicked = "rejected"
                if b3.form_submit_button("Override"):
                    clicked = "overridden"
                if clicked:
                    if not decided_by.strip():
                        st.warning("Please enter the manager name.")
                    else:
                        try:
                            api_post("/recommendation/decision", {
                                "order_id": order_id, "action": action["action"], "decision": clicked,
                                "comment": comment.strip() or None, "decided_by": decided_by.strip()})
                            st.success(f"Saved: {clicked} by {decided_by.strip()}")
                        except httpx.ConnectError:
                            backend_down()
                        except httpx.HTTPStatusError as e:
                            show_http_error(e, "Could not save the decision")

    if result["dropped_actions"]:
        with st.expander(f"Actions not recommended ({len(result['dropped_actions'])}): no supporting SOP"):
            for d in result["dropped_actions"]:
                st.write(f"- {d['action']} ({d['driver']})")

# ---------- past decisions ----------
st.subheader("Manager decisions for this order")
try:
    decisions = api_get(f"/recommendation/decisions/{order_id}")
    if decisions:
        st.dataframe(pd.DataFrame(decisions)[["decided_at", "action", "decision", "comment", "decided_by"]],
                     hide_index=True, width="stretch")
    else:
        st.caption("No decisions yet.")
except httpx.ConnectError:
    backend_down()
except httpx.HTTPStatusError as e:
    show_http_error(e, "Could not load decisions")

# ---------- knowledge base ----------
with st.expander("Knowledge base"):
    try:
        kb = api_get("/recommendation/kb")
        st.caption(f"{kb['document_count']} documents  |  backend: {kb['retrieval_backend']}  |  "
                   f"index: {kb['index_status']}" + (f" ({kb['index_built_at']})" if kb["index_built_at"] else ""))
        st.dataframe(pd.DataFrame(kb["documents"]), hide_index=True, width="stretch")
    except httpx.ConnectError:
        st.warning(f"Backend is not reachable at {API_URL}.")
    except httpx.HTTPStatusError as e:
        show_http_error(e, "Knowledge base unavailable")

with st.expander("Search the knowledge base"):
    query = st.text_input("Search query", placeholder="e.g. supplier delay")
    top_k = st.slider("Results", 1, 10, 3)
    if st.button("Search") and query.strip():
        try:
            found = api_post("/recommendation/search", {"query": query, "top_k": top_k})
            if not found["results"]:
                st.info("No matching document (all scores below the minimum).")
            for r in found["results"]:
                st.markdown(f"**{r['document_id']} – {r['title']}** ({r['category']}, score {r['score']:.2f})")
                st.write(r["text"])
        except httpx.ConnectError:
            st.warning(f"Backend is not reachable at {API_URL}.")
        except httpx.HTTPStatusError as e:
            show_http_error(e, "Search failed")
