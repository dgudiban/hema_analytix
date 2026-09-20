"""ORM entities: an uploaded Report and its parsed/analyzed Result rows.

Reference ranges are stored per result, exactly as printed on that report —
no universal ranges are hard-coded anywhere in the schema or the code.
"""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.db import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Date printed on the report (falls back to the upload date at capture).
    report_date = Column(Date, nullable=True)
    raw_text = Column(Text, nullable=True)

    results = relationship(
        "Result", back_populates="report", cascade="all, delete-orphan"
    )


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False, index=True)
    biomarker_id = Column(String(10), nullable=False, index=True)  # e.g. "BM001"
    standard_name = Column(String(120), nullable=False)
    # Test name exactly as written in the report (traceability).
    original_name = Column(String(120), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(60), nullable=False)
    # "LOW" | "NORMAL" | "HIGH" | "unknown" (no range printed on the report).
    status = Column(String(10), nullable=False)
    # Report-specific reference range; both null when the report has none.
    ref_low = Column(Float, nullable=True)
    ref_high = Column(Float, nullable=True)
    # The lab's own printed flag word (Low/High/Borderline/...), if any.
    flag = Column(String(12), nullable=True)
    # "reported" | "calculated"
    source = Column(String(12), nullable=False, default="reported")
    # Derivation description for calculated rows, e.g. "total_cholesterol − hdl".
    method = Column(Text, nullable=True)

    report = relationship("Report", back_populates="results")
