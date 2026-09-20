"""Historical trend engine.

Aligns a biomarker's results across dated reports and reports the direction
of change: "improving" (up), "declining" (down), or "stable". Only points
with mutually compatible units are compared; the rest are returned in
``excluded`` so the caller can explain why they were skipped.
"""
from app.models.entities import Report, Result
from app.utils.units import normalize_unit

TOLERANCE = 0.05  # 5% change band counts as stable


def _direction(values: list[float]) -> str:
    """improving/declining/stable from a chronological value series."""
    n = len(values)
    if n < 2:
        return "stable"
    if n == 2:
        first, second = values[0], values[-1]
    else:
        half = n // 2
        first = sum(values[:half]) / half
        second = sum(values[half:]) / (n - half)
    if first == 0:
        if second == 0:
            return "stable"
        return "improving" if second > 0 else "declining"
    change = (second - first) / abs(first)
    if abs(change) <= TOLERANCE:
        return "stable"
    return "improving" if change > 0 else "declining"


def get_trend(db, biomarker_id: str, user_id: int | None = None) -> dict | None:
    """Trend for *biomarker_id* across the patient's reports, oldest first.

    When *user_id* is given, only that patient's reports are considered.
    Returns None when the biomarker has no stored results.
    """
    q = (
        db.query(Result)
        .join(Report)
        .filter(Result.biomarker_id == biomarker_id)
    )
    if user_id is not None:
        q = q.filter(Report.user_id == user_id)
    rows = q.order_by(Report.report_date, Report.id).all()
    if not rows:
        return None

    baseline_unit = rows[0].unit
    points: list[dict] = []
    excluded: list[dict] = []
    for r in rows:
        report_date = r.report.report_date if r.report else None
        point = {
            "report_date": report_date.isoformat() if report_date else None,
            "value": r.value,
            "unit": r.unit,
            "ref_low": r.ref_low,
            "ref_high": r.ref_high,
            "status": r.status,
        }
        if normalize_unit(r.unit) == normalize_unit(baseline_unit):
            points.append(point)
        else:
            excluded.append(
                {
                    **point,
                    "reason": (
                        f"incompatible unit {r.unit!r} "
                        f"(baseline {baseline_unit!r})"
                    ),
                }
            )

    return {
        "biomarker_id": biomarker_id,
        "standard_name": rows[0].standard_name,
        "unit": baseline_unit,
        "points": points,
        "excluded": excluded,
        "direction": _direction([p["value"] for p in points]),
    }
