import pytest
from app.agents.order_analysis import OrderAnalysisAgent
from app.schemas.order import ExtractedOrder
from app.services.llm_client import LLMClient
from unittest.mock import Mock, patch

def test_extract_valid_order_message():
    mock_llm = Mock(spec=LLMClient)
    # 8 cases to test:
    # 1. basic message
    mock_llm.generate.return_value = '{"cus_ord_id": null, "product_type": "T-Shirt", "quantity": 20000, "priority": "High", "order_date": "2026-10-05", "deadline_date": "2026-10-15", "material_required": null}'
    agent = OrderAnalysisAgent(mock_llm)
    
    resp = agent.analyze_text("We need 20,000 cotton T-shirts by October 15 with high priority.")
    assert resp.status == "success"
    assert resp.extracted_order.quantity == 20000
    assert resp.extracted_order.priority == "High"
    
def test_missing_fields_needs_clarification():
    mock_llm = Mock(spec=LLMClient)
    mock_llm.generate.return_value = '{"cus_ord_id": null, "product_type": null, "quantity": null, "priority": "Medium", "order_date": "2026-10-05", "deadline_date": null, "material_required": null}'
    agent = OrderAnalysisAgent(mock_llm)
    
    resp = agent.analyze_text("Hello")
    assert resp.status == "needs_clarification"
    assert "quantity" in resp.missing_fields
    assert "product_type" in resp.missing_fields
