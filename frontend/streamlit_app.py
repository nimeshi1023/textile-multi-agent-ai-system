import streamlit as st

st.set_page_config(page_title="FabricFlow", layout="wide")

st.sidebar.title("FabricFlow")
st.sidebar.page_link("streamlit_app.py", label="Home")
st.sidebar.page_link("pages/new_order.py", label="New Order")
st.sidebar.page_link("pages/orders.py", label="Orders")

st.sidebar.subheader("Other Agents (Coming Soon)")
st.sidebar.button("Resource & Production", disabled=True)
st.sidebar.button("Delay Risk", disabled=True)
st.sidebar.button("Recommendations", disabled=True)

st.title("Welcome to FabricFlow")
st.markdown("A multi-agent garment manufacturing order management system.")
