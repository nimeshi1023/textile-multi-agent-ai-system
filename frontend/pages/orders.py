import streamlit as st
import pandas as pd
from api_client import get_orders, delete_order
from auth_ui import require_login, render_user_sidebar

require_login()
render_user_sidebar()
st.title("Orders")

col1, col2 = st.columns(2)
with col1:
    priority_filter = st.selectbox("Filter by Priority", ["All", "Low", "Medium", "High"])

if st.button("Refresh"):
    st.rerun()

try:
    orders = get_orders(priority=priority_filter)
    if not orders:
        st.info("No orders found.")
    else:
        df = pd.DataFrame(orders)
        st.dataframe(df)
        
        # Simple Delete functionality
        del_id = st.text_input("Enter Order ID to delete")
        if st.button("Delete"):
            try:
                delete_order(del_id)
                st.success("Deleted!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to delete: {e}")
                
except Exception as e:
    st.error(f"Failed to load orders: {e}")
