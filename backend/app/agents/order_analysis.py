import json
from decimal import Decimal
from typing import Optional
from datetime import date, datetime
from app.schemas.order import ExtractedOrder, OrderAnalysisResponse
from app.services.llm_client import LLMClient
from pydantic import ValidationError

class OrderAnalysisAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def analyze_text(self, text: str) -> OrderAnalysisResponse:
        today = date.today().isoformat()
        prompt = f"""
You are an expert order extraction agent for a garment manufacturing system.
Today's date is {today}.

Extract the order details from the following text into a JSON object matching this schema EXACTLY:
- cus_ord_id: string (max 20 chars) or null. Extract only if an order/PO number is stated.
- product_type: string. Normalize to standard names (e.g., "T-Shirt", "Polo Shirt", "Shirt", "Trousers", "Jacket", "Hoodie").
- quantity: integer (> 0). Normalize values like "20k" to 20000.
- priority: "Low", "Medium", or "High". Default to "Medium" if not mentioned.
- order_date: string (YYYY-MM-DD) or null. If relative (e.g. "today"), resolve using today's date.
- deadline_date: string (YYYY-MM-DD). Resolve relative dates using today's date.
- material_required: float (2 decimal places) or null. Extract ONLY if explicitly stated (e.g. "needs 30000 meters"). Do not calculate or estimate it.
- material_name: string or null. Extract the name of the fabric or material if explicitly stated (e.g. "blended fabric", "cotton").

Rules:
1. Extract ONLY what is stated.
2. Return null for missing fields (except for priority which defaults to "Medium").
3. Do not invent values.
4. If the year for a date is missing, use the next upcoming occurrence.

Text:
\"\"\"{text}\"\"\"
"""
        max_retries = 2
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response_text = self.llm_client.generate(prompt)
                data = json.loads(response_text)
                extracted = ExtractedOrder(**data)
                
                missing = []
                # Pydantic checks presence for required fields but if the model hallucinated null we should check
                if extracted.product_type is None or str(extracted.product_type).strip() == "":
                    missing.append("product_type")
                if extracted.quantity is None or extracted.quantity <= 0:
                    missing.append("quantity")
                if extracted.deadline_date is None:
                    missing.append("deadline_date")
                
                if missing:
                    return OrderAnalysisResponse(
                        status="needs_clarification",
                        missing_fields=missing,
                        extracted_order=extracted
                    )
                
                return OrderAnalysisResponse(
                    status="success",
                    extracted_order=extracted
                )
                
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)
                prompt += f"\n\nValidation Error on previous attempt: {last_error}\nPlease fix the JSON and ensure it conforms to the schema."
            except Exception as e:
                return OrderAnalysisResponse(status="error", error_message=str(e))
                
        return OrderAnalysisResponse(status="error", error_message=f"Failed after {max_retries} retries: {last_error}")

    def analyze_pdf(self, pdf_file_content: bytes, extracted_text: str | None = None) -> OrderAnalysisResponse:
        if extracted_text and extracted_text.strip():
            return self.analyze_text(extracted_text)
        
        # Multimodal fallback
        today = date.today().isoformat()
        prompt = f"""
You are an expert order extraction agent for a garment manufacturing system.
Today's date is {today}.

Extract the order details from the provided document into a JSON object matching this schema EXACTLY:
- cus_ord_id: string (max 20 chars) or null. Extract only if an order/PO number is stated.
- product_type: string. Normalize to standard names (e.g., "T-Shirt", "Polo Shirt", "Shirt", "Trousers", "Jacket", "Hoodie").
- quantity: integer (> 0). Normalize values like "20k" to 20000.
- priority: "Low", "Medium", or "High". Default to "Medium" if not mentioned.
- order_date: string (YYYY-MM-DD) or null. If relative (e.g. "today"), resolve using today's date.
- deadline_date: string (YYYY-MM-DD). Resolve relative dates using today's date.
- material_required: float (2 decimal places) or null. Extract ONLY if explicitly stated.
- material_name: string or null. Extract the name of the fabric or material if explicitly stated.

Rules:
1. Extract ONLY what is stated.
2. Return null for missing fields.
3. Do not invent values.
4. If the year for a date is missing, use the next upcoming occurrence.
"""
        try:
            response_text = self.llm_client.generate_multimodal(prompt, pdf_file_content, "application/pdf")
            data = json.loads(response_text)
            extracted = ExtractedOrder(**data)
            
            missing = []
            if extracted.product_type is None or str(extracted.product_type).strip() == "":
                missing.append("product_type")
            if extracted.quantity is None or extracted.quantity <= 0:
                missing.append("quantity")
            if extracted.deadline_date is None:
                missing.append("deadline_date")
            
            if missing:
                return OrderAnalysisResponse(
                    status="needs_clarification",
                    missing_fields=missing,
                    extracted_order=extracted
                )
            
            return OrderAnalysisResponse(
                status="success",
                extracted_order=extracted
            )
        except Exception as e:
            return OrderAnalysisResponse(status="error", error_message=str(e))
