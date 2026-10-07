from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date

class ResourceAnalyzeRequest(BaseModel):
    order_id: Optional[str] = None
    product_type: Optional[str] = None
    quantity: Optional[int] = None
    deadline_date: Optional[date] = None
    material_name: Optional[str] = None
    priority: Optional[str] = None
    failed_machine_id: Optional[str] = None

class MachineInfo(BaseModel):
    machine_id: str
    machine_capacity_per_day: float
    machine_current_workload_pct: float
    status: str

class MaterialInfo(BaseModel):
    material_name: str
    stock_qty: float
    usage_per_unit: float
    reorder_lead_time_days: int
    supplier_id: Optional[str]

class SupplierInfo(BaseModel):
    supplier_id: str
    avg_lead_time_days: int
    reliability_score: float

class ResourceCalculations(BaseModel):
    days_remaining: int
    material_required: float
    material_available: float
    available_capacity_per_day: float
    required_production_days: float
    capacity_in_deadline: float
    capacity_shortfall: float
    tight_deadline: bool

class ResourceAnalyzeResponse(BaseModel):
    order_id: str
    resource_status: str
    issues: List[str]
    machine: Optional[dict] = None
    material: Optional[dict] = None
    supplier: Optional[dict] = None
    calculations: Optional[ResourceCalculations] = None
    explanation: str
    explanation_source: str
    data_source: str = "postgresql"
