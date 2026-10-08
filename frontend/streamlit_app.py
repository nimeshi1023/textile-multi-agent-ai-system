import html

import streamlit as st

from auth_ui import render_user_sidebar, require_login

st.set_page_config(page_title="FabricFlow", layout="wide")

manager = require_login()
render_user_sidebar()

st.sidebar.title("FabricFlow")
st.sidebar.page_link("streamlit_app.py", label="Home")
st.sidebar.page_link("pages/new_order.py", label="New Order")
st.sidebar.page_link("pages/orders.py", label="Orders")

st.title(f"Welcome, {manager['manager_id']}")
st.caption(f"{manager['manager_type']}  ·  FabricFlow – Multi-Agent AI for Textile Production")

st.markdown("#### How an order flows through FabricFlow")
steps = [
    ("1", "Order Analysis", "Reads a customer message or PDF and extracts product, quantity, priority and deadline.",
     "New Order"),
    ("2", "Resource & Production", "Checks machine capacity, material stock and suppliers for the order.",
     "New Order"),
    ("3", "Delay Prediction", "A Random Forest model estimates the delay risk and explains the main factors.",
     "Delay Prediction"),
    ("4", "Recommendation", "Suggests SOP-backed actions from the knowledge base; you approve, reject or override.",
     "Recommendation"),
]
for column, (number, title, text, page) in zip(st.columns(4), steps):
    with column, st.container(border=True):
        st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:#E0A030'>STEP {number}</div>",
                    unsafe_allow_html=True)
        st.markdown(f"**{html.escape(title)}**")
        st.write(text)
        st.caption(f"Page: {page}")

st.info("AI agents recommend; the manager decides. Every recommended action needs your approval.")
