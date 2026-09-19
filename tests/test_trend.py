"""Trend-engine tests: direction rules and unit-compatibility exclusion.

Uses synthetic biomarker ids (BM901+) written straight to the test DB so the
results are fully isolated from the API-flow tests.
"""
from datetime import date

import pytest

from app.models.db import SessionLocal
from app.models.entities import Report, Result
from app.services import trend_service


def _seed(biomarker_id, standard_name, points):
    """Write one report per point; points = [(date, value, unit), ...]."""
    db = SessionLocal()
    try:
        for i, (d, value, unit) in enumerate(points):
            report = Report(
                filename=f"trend_{biomarker_id}_{i}.pdf",
                report_date=d,
                raw_text="",
            )
            db.add(report)
            db.flush()
            db.add(
                Result(
                    report_id=report.id,
                    biomarker_id=biomarker_id,
                    standard_name=standard_name,
                    original_name=standard_name,
                    value=value,
                    unit=unit,
                    status="NORMAL",
                    ref_low=None,
                    ref_high=None,
                    source="reported",
                    method=None,
                )
            )
        db.commit()
    finally:
        db.close()


def _trend(biomarker_id):
    db = SessionLocal()
    try:
        return trend_service.get_trend(db, biomarker_id)
    finally:
        db.close()


def test_direction_improving():
    _seed(
        "BM901", "Hemoglobin",
        [(date(2026, 1, 15), 10.8, "g/dL"), (date(2026, 3, 15), 11.2, "g/dL"),
         (date(2026, 6, 15), 11.8, "g/dL"), (date(2026, 8, 15), 12.1, "g/dL")],
    )
    trend = _trend("BM901")
    assert trend["direction"] == "improving"
    assert [p["value"] for p in trend["points"]] == [10.8, 11.2, 11.8, 12.1]
    assert trend["points"][0]["report_date"] == "2026-01-15"
    assert trend["excluded"] == []


def test_direction_declining():
    _seed(
        "BM902", "Hemoglobin",
        [(date(2026, 1, 15), 12.1, "g/dL"), (date(2026, 3, 15), 11.8, "g/dL"),
         (date(2026, 6, 15), 11.2, "g/dL"), (date(2026, 8, 15), 10.8, "g/dL")],
    )
    assert _trend("BM902")["direction"] == "declining"


def test_direction_stable_within_tolerance():
    _seed(
        "BM903", "Hemoglobin",
        [(date(2026, 1, 15), 13.2, "g/dL"), (date(2026, 3, 15), 13.3, "g/dL"),
         (date(2026, 6, 15), 13.25, "g/dL")],
    )
    assert _trend("BM903")["direction"] == "stable"


def test_two_points_uses_first_vs_last():
    _seed(
        "BM904", "Glucose",
        [(date(2026, 1, 15), 95.0, "mg/dL"), (date(2026, 6, 15), 115.0, "mg/dL")],
    )
    assert _trend("BM904")["direction"] == "improving"
    _seed(
        "BM905", "Glucose",
        [(date(2026, 1, 15), 100.0, "mg/dL"), (date(2026, 6, 15), 102.0, "mg/dL")],
    )
    assert _trend("BM905")["direction"] == "stable"  # 2% < 5% tolerance


def test_single_point_is_stable():
    _seed("BM906", "Glucose", [(date(2026, 1, 15), 95.0, "mg/dL")])
    trend = _trend("BM906")
    assert trend["direction"] == "stable"
    assert len(trend["points"]) == 1


def test_incompatible_units_excluded():
    _seed(
        "BM907", "Hemoglobin",
        [(date(2026, 1, 15), 11.0, "g/dL"), (date(2026, 6, 15), 110.0, "g/L")],
    )
    trend = _trend("BM907")
    assert len(trend["points"]) == 1
    assert trend["points"][0]["unit"] == "g/dL"
    assert len(trend["excluded"]) == 1
    assert "incompatible unit" in trend["excluded"][0]["reason"]
    assert trend["excluded"][0]["value"] == pytest.approx(110.0)


def test_compatible_unit_variants_included():
    _seed(
        "BM908", "WBC",
        [(date(2026, 1, 15), 6500.0, "K/µL"), (date(2026, 6, 15), 7000.0, "K/uL")],
    )
    trend = _trend("BM908")
    assert len(trend["points"]) == 2
    assert trend["excluded"] == []


def test_no_data_returns_none():
    db = SessionLocal()
    try:
        assert trend_service.get_trend(db, "BM900") is None
    finally:
        db.close()
