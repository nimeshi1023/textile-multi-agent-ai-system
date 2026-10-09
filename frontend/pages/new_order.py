import streamlit as st
import httpx
from datetime import date
from api_client import analyze_message, analyze_pdf, create_order, analyze_resources
from auth_ui import require_login, render_user_sidebar

require_login()
render_user_sidebar()
st.title("New Order")


mode = st.radio("Input Method", ["Type a message", "Upload PDF"])

if "analysis" not in st.session_state:
    st.session_state.analysis = None

if mode == "Type a message":
    text = st.text_area("Order Message")
    if st.button("Analyze"):
        with st.spinner("Analyzing message..."):
            try:
                result = analyze_message(text)
                st.session_state.analysis = result
            except Exception as e:
                st.error(f"Error: {e}")
                
else:
    uploaded_file = st.file_uploader("Upload Purchase Order", type=["pdf"])
    if st.button("Analyze") and uploaded_file:
        if uploaded_file.size > 10 * 1024 * 1024:
            st.error("File size exceeds 10 MB limit")
        else:
            with st.spinner("Analyzing PDF..."):
                try:
                    result = analyze_pdf(uploaded_file.getvalue(), uploaded_file.name)
                    st.session_state.analysis = result
                except Exception as e:
                    st.error(f"Error: {e}")

if st.session_state.analysis:
    analysis = st.session_state.analysis
    
    if analysis.get("status") == "error":
        st.error(f"LLM Error: {analysis.get('error_message')}")
    else:
        if analysis.get("status") == "needs_clarification":
            st.warning(f"Needs clarification. Missing fields: {', '.join(analysis.get('missing_fields', []))}. Please fill them manually.")
        else:
            st.success("Successfully analyzed!")
            
        ext = analysis.get("extracted_order", {})
        
        with st.form("order_form"):
            product_type = st.text_input("Product Type", value=ext.get("product_type") or "")
            
            quantity_val = ext.get("quantity")
            quantity = st.number_input("Quantity", min_value=1, value=quantity_val if quantity_val else 1)
            
            priority_idx = {"Low": 0, "Medium": 1, "High": 2}.get(ext.get("priority"), 1)
            priority = st.selectbox("Priority", ["Low", "Medium", "High"], index=priority_idx)
            
            order_date_str = ext.get("order_date")
            order_date = st.date_input("Order Date", value=date.fromisoformat(order_date_str) if order_date_str else date.today())
            
            deadline_str = ext.get("deadline_date")
            deadline_date = st.date_input("Deadline Date", value=date.fromisoformat(deadline_str) if deadline_str else date.today())
            
            mat_val = ext.get("material_required")
            mat_src = analysis.get("material_required_source")
            
            if mat_src == "missing":
                st.warning("Material required is missing - please enter")
                
            label_suffix = f"[{mat_src.capitalize()}]" if mat_src else ""
            material_required = st.number_input(f"Material Required (meters) {label_suffix}", min_value=0.0, format="%.2f", value=float(mat_val) if mat_val is not None else 0.0)
            
            material_name_val = ext.get("material_name")
            material_name = st.text_input("Material Name", value=material_name_val if material_name_val else "")
            
            if st.form_submit_button("Confirm & Save to Database"):
                try:
                    payload = {
                        "cus_ord_id": "",
                        "product_type": product_type,
                        "quantity": quantity,
                        "priority": priority,
                        "order_date": order_date.isoformat(),
                        "deadline_date": deadline_date.isoformat(),
                        "material_required": str(material_required) if material_required > 0 else None,
                        "material_name": material_name if material_name else None
                    }
                    saved = create_order(payload)
                    st.success(f"Order saved successfully! ID: {saved.get('cus_ord_id')}")
                    
                    with st.spinner("Analyzing resources for production..."):
                        try:
                            res_data = analyze_resources({"order_id": saved.get('cus_ord_id')})
                            st.info(f"Resource Status: {res_data.get('resource_status')}")
                            if res_data.get('issues'):
                                st.warning(f"Issues: {', '.join(res_data.get('issues'))}")
                            st.write(res_data.get('explanation'))
                        except Exception as e:
                            st.error(f"Resource analysis failed: {e}")
                            
                    st.session_state.analysis = None # reset
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 409:
                        st.error(f"Duplicate Order ID: {cus_ord_id} already exists.")
                    else:
                        st.error(f"API Error: {e.response.text}")
                except Exception as e:
                    st.error(f"Error: {e}")
