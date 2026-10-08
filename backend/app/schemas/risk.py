from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class OrderFacts(BaseModel):
    """Order facts not contained in the Resource Agent result."""
    product_type: Optional[str] = None
    quantity: Optional[int] = Field(default=None, gt=0)
    priority: Optional[str] = None


class RiskPredictRequest(BaseModel):
    order_id: Optional[str] = None
    resource_result: Optional[Dict[str, Any]] = None
    order: Optional[OrderFacts] = None

    @model_validator(mode="after")
    def require_input(self):
        if not self.order_id and not self.resource_result:
            raise ValueError("Provide either 'order_id' or 'resource_result'.")
        return self


class TopFactor(BaseModel):
    feature: str
    value: Any
    direction: str
    impact: float


class Thresholds(BaseModel):
    low_max: float
    medium_max: float


class ModelSummary(BaseModel):
    name: str
    trained_at: str
    roc_auc: float
    calibrated: bool = False


class RiskPredictResponse(BaseModel):
    order_id: str
    delay_probability: float
    delay_probability_pct: float
    risk_level: str
    thresholds: Thresholds
    top_factors: List[TopFactor]
    risk_drivers: List[str]
    explanation: str
    explanation_source: str
    input_features: Dict[str, Any]
    missing_features: List[str]
    model: ModelSummary
    data_source: str = "postgresql"
