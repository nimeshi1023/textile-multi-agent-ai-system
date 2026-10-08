import json
import logging
from decimal import Decimal
from typing import Optional
from datetime import date, datetime
from app.schemas.order import ExtractedOrder, OrderAnalysisResponse
from app.services.llm_client import LLMClient
from pydantic import ValidationError

logger = logging.getLogger(__name__)

# Standard material names (same as the `materials` table). Used if the table cannot be read.
DEFAULT_MATERIAL_NAMES = [
    "Silk Thread", "Linen Fabric", "Elastane Mix", "Polyester Fabric", "Dyed Cotton",
    "Viscose Fabric", "Denim Cloth", "Wool Blend", "Bleached Cloth",
]

# Keyword in the customer's wording -> standard material name
MATERIAL_KEYWORDS = [
    ("denim", "Denim Cloth"),
    ("silk", "Silk Thread"),
    ("linen", "Linen Fabric"),
    ("elastane", "Elastane Mix"), ("spandex", "Elastane Mix"), ("lycra", "Elastane Mix"),
    ("polyester", "Polyester Fabric"),
    ("viscose", "Viscose Fabric"), ("rayon", "Viscose Fabric"),
    ("wool", "Wool Blend"),
    ("bleach", "Bleached Cloth"),
    ("cotton", "Dyed Cotton"),
]

_material_names_cache: Optional[list] = None


def load_material_names() -> list:
    """Distinct material names from the `materials` table (read-only, cached)."""
    global _material_names_cache
    if _material_names_cache is None:
        try:
            from sqlalchemy import text
            from app.db.session import engine
            with engine.connect() as conn:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                rows = conn.execute(text(
                    "SELECT DISTINCT TRIM(material_name) FROM materials WHERE material_name IS NOT NULL ORDER BY 1"
                )).fetchall()
            _material_names_cache = [r[0] for r in rows] or DEFAULT_MATERIAL_NAMES
        except Exception as e:
            logger.warning(f"Could not read material names, using defaults: {e}")
            return DEFAULT_MATERIAL_NAMES
    return _material_names_cache


def normalize_material_name(name: Optional[str], known_names: Optional[list] = None) -> Optional[str]:
    """Map the customer's wording to a standard material name, e.g. "denim fabric" -> "Denim Cloth".
    Unknown materials are returned unchanged (never guessed)."""
    if name is None or not str(name).strip():
        return None
    known = known_names or load_material_names()
    cleaned = " ".join(str(name).split())
    by_lower = {k.lower(): k for k in known}
    if cleaned.lower() in by_lower:                     # exact match, any letter case
        return by_lower[cleaned.lower()]
    lowered = cleaned.lower()
    for keyword, standard in MATERIAL_KEYWORDS:         # e.g. "denim fabric" contains "denim"
        if keyword in lowered and standard.lower() in by_lower:
            return by_lower[standard.lower()]
    return cleaned


class OrderAnalysisAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    @staticmethod
    def _normalize(extracted: ExtractedOrder) -> ExtractedOrder:
        extracted.material_name = normalize_material_name(extracted.material_name)
        return extracted

    def analyze_text(self, text: str) -> OrderAnalysisResponse:
        today = date.today().isoformat()
        materials = ", ".join(f'"{m}"' for m in load_material_names())
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
- material_name: string or null. Extract the fabric or material only if explicitly stated, and normalize it to one of these standard names: {materials} (e.g. "denim fabric" -> "Denim Cloth", "cotton" -> "Dyed Cotton"). If it matches none of them, return it as written.

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
                extracted = self._normalize(ExtractedOrder(**data))

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
        materials = ", ".join(f'"{m}"' for m in load_material_names())
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
- material_name: string or null. Extract the fabric or material only if explicitly stated, and normalize it to one of these standard names: {materials} (e.g. "denim fabric" -> "Denim Cloth"). If it matches none of them, return it as written.

Rules:
1. Extract ONLY what is stated.
2. Return null for missing fields.
3. Do not invent values.
4. If the year for a date is missing, use the next upcoming occurrence.
"""
        try:
            response_text = self.llm_client.generate_multimodal(prompt, pdf_file_content, "application/pdf")
            data = json.loads(response_text)
            extracted = self._normalize(ExtractedOrder(**data))
            
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
