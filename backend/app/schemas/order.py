from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import date
from decimal import Decimal

class ExtractedOrder(BaseModel):
    cus_ord_id: Optional[str] = Field(None, max_length=20, description="Order/PO number if stated")
    product_type: str = Field(..., description="Normalized product type")
    quantity: int = Field(..., gt=0, description="Quantity")
    priority: Literal["Low", "Medium", "High"] = Field("Medium", description="Priority level")
    order_date: Optional[date] = Field(None, description="Order date")
    deadline_date: date = Field(..., description="Deadline date")
    material_required: Optional[Decimal] = Field(None, ge=0, decimal_places=2, description="Material required in meters")
    material_name: Optional[str] = Field(None, max_length=50, description="Material name")

class OrderAnalysisResponse(BaseModel):
    extracted_order: ExtractedOrder | None = None
    status: Literal["success", "needs_clarification", "error"]
    missing_fields: list[str] = []
    material_required_source: Literal["extracted", "estimated", "missing"] | None = None
    error_message: str | None = None

class OrderCreate(ExtractedOrder):
    cus_ord_id: str = Field(..., max_length=20)
    order_date: date

class OrderUpdate(BaseModel):
    product_type: Optional[str] = None
    quantity: Optional[int] = None
    priority: Optional[Literal["Low", "Medium", "High"]] = None
    order_date: Optional[date] = None
    deadline_date: Optional[date] = None
    material_required: Optional[Decimal] = None

class OrderResponse(OrderCreate):
    class Config:
        from_attributes = True

class MessageRequest(BaseModel):
    text: str
