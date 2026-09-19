"""Pydantic request/response models (DTOs)."""
from datetime import date, datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class BiomarkerSpec(BaseModel):
    biomarker_id: str
    standard_name: str
    category: str
    common_aliases: list[str]
    typical_units: str
    description: str
    supports_trend: bool
    calculation_type: str
    special_handling: str


class UploadResponse(BaseModel):
    report_id: int
    filename: str
    report_date: date | None = None
    text_preview: str
    pages: int
    note: str | None = None


class ResultOut(BaseModel):
    biomarker_id: str
    standard_name: str
    original_name: str
    value: float
    unit: str
    status: str  # "LOW" | "NORMAL" | "HIGH" | "unknown"
    ref_low: float | None = None
    ref_high: float | None = None
    source: str  # "reported" | "calculated"
    method: str | None = None


class AnalyzeResponse(BaseModel):
    report_id: int
    results: list[ResultOut]
    summary: str
    ai_explanation: str | None = None


class ReportSummary(BaseModel):
    id: int
    filename: str
    report_date: date | None = None
    uploaded_at: datetime
    result_count: int


class ReportDetail(BaseModel):
    id: int
    filename: str
    report_date: date | None = None
    uploaded_at: datetime
    results: list[ResultOut]


class TrendPoint(BaseModel):
    report_date: str | None
    value: float
    unit: str


class TrendExcludedPoint(TrendPoint):
    reason: str


class TrendResponse(BaseModel):
    biomarker_id: str
    standard_name: str
    unit: str
    points: list[TrendPoint]
    excluded: list[TrendExcludedPoint] = []
    direction: str  # "improving" | "declining" | "stable"
