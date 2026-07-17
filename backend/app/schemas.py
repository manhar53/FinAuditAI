"""Pydantic models = FastAPI's request/response contracts.

FastAPI validates incoming JSON against these automatically and uses them
to serialize ORM objects out (model_config from_attributes=True), and they
drive the auto-generated OpenAPI docs at /docs.
"""
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict


class LineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class AnomalyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    rule_code: str
    severity: str
    score: Optional[float] = None
    explanation: str
    details: Optional[dict[str, Any]] = None
    status: str
    created_at: Optional[datetime] = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_type: str
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    category: Optional[str] = None
    status: str
    extraction_method: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class DocumentDetail(DocumentOut):
    line_items: list[LineItemOut] = []
    anomalies: list[AnomalyOut] = []


class UploadResult(BaseModel):
    documents_created: int
    anomalies_flagged: int
    document_ids: list[int]
    anomaly_summaries: list[str]


class AnomalyStatusUpdate(BaseModel):
    status: Literal["open", "reviewed", "dismissed"]


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str
    tool_used: str
    rows: list[dict[str, Any]] = []
