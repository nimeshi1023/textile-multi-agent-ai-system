from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class GenerateRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=20)
    # Optional: pass earlier agents' results instead of recomputing them
    risk_result: Optional[Dict[str, Any]] = None
    resource_result: Optional[Dict[str, Any]] = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=3, ge=1, le=10)
    category: Optional[str] = None

    @field_validator("query")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be blank")
        return v.strip()


class DecisionRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=20)
    action: str = Field(min_length=1, max_length=200)
    decision: Literal["approved", "rejected", "overridden"]
    comment: Optional[str] = Field(default=None, max_length=2000)
    decided_by: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def override_needs_comment(self):
        if self.decision == "overridden" and not (self.comment and self.comment.strip()):
            raise ValueError("An override needs a comment describing the manager's own action.")
        return self


class Source(BaseModel):
    document_id: str
    title: str
    score: float


class RecommendedAction(BaseModel):
    rank: int
    action: str
    drivers: List[str]
    reason: str
    sources: List[Source]
    requires_manager_approval: bool = True


class RetrievedDocument(BaseModel):
    document_id: str
    title: str
    category: str
    tags: List[str]
    text: str
    score: float
    source_file: str


class RecommendationResponse(BaseModel):
    order_id: str
    status: Literal["no_action_needed", "recommendations_ready", "no_supported_actions"]
    risk_level: str
    delay_probability_pct: float
    drivers: List[str]
    actions: List[RecommendedAction]
    dropped_actions: List[Dict[str, str]]
    retrieved_documents: List[RetrievedDocument]
    explanation: str
    explanation_source: str
    retrieval_backend: Optional[str]
    data_source: str = "postgresql"


class DecisionRecord(BaseModel):
    id: int
    order_id: str
    action: str
    decision: str
    comment: Optional[str]
    decided_by: str
    decided_at: datetime
