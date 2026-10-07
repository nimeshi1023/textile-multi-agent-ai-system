import pytest
from datetime import date, timedelta
from app.agents.resource_production import ResourceProductionAgent
from app.schemas.resource import ResourceAnalyzeRequest, MachineInfo, MaterialInfo, SupplierInfo, ResourceCalculations
from unittest.mock import MagicMock

class MockDB:
    pass

@pytest.fixture
def agent():
    db = MockDB()
    a = ResourceProductionAgent(db)
    # Mock LLM client so it doesn't try to call Gemini
    a.llm_client.generate = MagicMock(return_value='{"explanation": "Mocked LLM Explanation containing 20000"}')
    return a

def test_pure_calculations(agent):
    data = {
        'order': {
            'quantity': 20000,
            'deadline_date': date.today() + timedelta(days=10),
            'order_date': date.today(),
        },
        'machine': MachineInfo(
            machine_id="MCH01",
            machine_capacity_per_day=1500,
            machine_current_workload_pct=0.0,
            status="Operational"
        ),
        'material': MaterialInfo(
            material_name="Cotton",
            stock_qty=3000.0,
            usage_per_unit=0.25,
            reorder_lead_time_days=5,
            supplier_id="SUP01"
        ),
        'supplier': SupplierInfo(
            supplier_id="SUP01",
            avg_lead_time_days=5,
            reliability_score=0.9
        )
    }

    calcs, issues = agent.calculate(data)
    assert calcs.days_remaining == 10
    assert calcs.material_required == 5000.0
    assert calcs.material_available == -2000.0
    assert "MATERIAL_SHORTAGE" in issues
    assert "MACHINE_CAPACITY_SHORTAGE" in issues
    assert round(calcs.required_production_days, 2) == 13.33

def test_unknown_material(agent):
    req = ResourceAnalyzeRequest(order_id="ORD1", quantity=100)
    agent.fetch_data = MagicMock(return_value={"issue": "MATERIAL_NOT_FOUND"})
    res = agent.run(req)
    assert res.resource_status == "INSUFFICIENT"
    assert "MATERIAL_NOT_FOUND" in res.issues
    assert res.explanation_source == "template"

def test_failed_machine_unavailable(agent):
    data = {
        'order': {
            'quantity': 100,
            'deadline_date': date.today() + timedelta(days=10),
            'order_date': date.today(),
        },
        'machine': None
    }
    calcs, issues = agent.calculate(data)
    assert "MACHINE_UNAVAILABLE" in issues
    assert calcs.required_production_days == float('inf')

def test_capacity_zero_no_division_error(agent):
    data = {
        'order': {
            'quantity': 100,
            'deadline_date': date.today() + timedelta(days=10),
            'order_date': date.today(),
        },
        'machine': MachineInfo(
            machine_id="MCH01",
            machine_capacity_per_day=0,
            machine_current_workload_pct=0.0,
            status="Operational"
        )
    }
    calcs, issues = agent.calculate(data)
    assert "MACHINE_CAPACITY_SHORTAGE" in issues
    assert calcs.required_production_days == float('inf')

def test_llm_wrong_numbers_fallback(agent):
    data = {
        'order': {'quantity': 20000, 'deadline_date': date.today() + timedelta(days=10), 'order_date': date.today()}
    }
    calcs = ResourceCalculations(
        days_remaining=10,
        material_required=5000,
        material_available=-2000,
        available_capacity_per_day=1500,
        required_production_days=13.33,
        capacity_in_deadline=15000,
        capacity_shortfall=5000,
        tight_deadline=True
    )
    # LLM returns something unrelated to the numbers
    agent.llm_client.generate = MagicMock(return_value='{"explanation": "Everything is great!"}')
    exp, src = agent.explain(data, calcs, ["MATERIAL_SHORTAGE"])
    assert src == "template"
    assert "Everything is great!" not in exp

def test_sufficient_order(agent):
    data = {
        'order': {
            'quantity': 1000,
            'deadline_date': date.today() + timedelta(days=10),
            'order_date': date.today(),
        },
        'machine': MachineInfo(
            machine_id="MCH01",
            machine_capacity_per_day=1500,
            machine_current_workload_pct=0.0,
            status="Operational"
        ),
        'material': MaterialInfo(
            material_name="Cotton",
            stock_qty=3000.0,
            usage_per_unit=0.25,
            reorder_lead_time_days=5,
            supplier_id="SUP01"
        )
    }
    calcs, issues = agent.calculate(data)
    assert len(issues) == 0
