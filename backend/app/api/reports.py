"""Report endpoints: upload, analyze, list, fetch, and trends.

Every endpoint requires a logged-in patient and only ever touches that
patient's own reports — no cross-account data is reachable.
"""
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.models.db import get_db
from app.models.entities import Report, Result, User
from app.schemas.dto import (
    AnalyzeResponse,
    CompareResponse,
    ReportDetail,
    ReportSummary,
    TrendResponse,
    UploadResponse,
)
from app.services import (
    ai_extract_service,
    ai_service,
    analysis_service,
    normalize_service,
    parse_service,
    pdf_service,
    trend_service,
)
from app.utils.dates import parse_report_date
from app.utils.spec import get_biomarkers

router = APIRouter()


def _owned_report(db: Session, report_id: int, user: User) -> Report:
    report = db.get(Report, report_id)
    if report is None or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report


@router.post("/upload", response_model=UploadResponse)
async def upload_report(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in pdf_service.ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400, detail="Only PDF and image files (JPG, PNG) are accepted."
        )
    try:
        saved_path = pdf_service.save_upload(file.filename, file.file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ingested = pdf_service.ingest(saved_path)
    text, pages, notes = ingested["text"], ingested["pages"], ingested["notes"]
    report_date = parse_report_date(text, fallback=date.today())

    report = Report(
        user_id=user.id,
        filename=saved_path.name,
        raw_text=text,
        report_date=report_date,
        source_type=ingested["source_type"],
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return {
        "report_id": report.id,
        "filename": report.filename,
        "report_date": report.report_date,
        "text_preview": text[:300],
        "pages": pages,
        "note": "; ".join(notes) if notes else None,
        "source_type": ingested["source_type"],
    }


@router.post("/{report_id}/analyze", response_model=AnalyzeResponse)
def analyze_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = _owned_report(db, report_id, user)

    # AI transcription first (transcribes printed facts only — status stays
    # deterministic); rule-based parser is the automatic fallback.
    parsed, extraction_source = ai_extract_service.extract(
        report.raw_text or "", get_biomarkers()
    )
    report.extraction_source = extraction_source
    normalized = normalize_service.normalize(parsed)
    with_calculated = normalize_service.add_calculated(normalized)
    analyzed = analysis_service.analyze(with_calculated)

    # Re-analysis replaces previous results (idempotent).
    db.query(Result).filter(Result.report_id == report.id).delete()
    for item in analyzed:
        db.add(
            Result(
                report_id=report.id,
                biomarker_id=item["biomarker_id"],
                standard_name=item["standard_name"],
                original_name=item["original_name"],
                value=item["value"],
                unit=item["unit"],
                status=item["status"],
                ref_low=item.get("ref_low"),
                ref_high=item.get("ref_high"),
                flag=item.get("flag"),
                source=item["source"],
                method=item.get("method"),
            )
        )
    db.commit()

    summary = analysis_service.summarize(
        analyzed, interpretation=parse_service.extract_interpretation(report.raw_text or "")
    )
    ai_explanation = ai_service.explain_report(analyzed, summary)

    return {
        "report_id": report.id,
        "results": analyzed,
        "summary": summary,
        "ai_explanation": ai_explanation,
        "extraction_source": extraction_source,
        "extraction_detail": ai_extract_service.last_run,
    }


# Registered BEFORE /{report_id} so the literal "trends" segment can never
# collide with a report id (report_id is int-typed anyway).
@router.get("/trends/{biomarker_id}", response_model=TrendResponse)
def get_trend(
    biomarker_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trend = trend_service.get_trend(db, biomarker_id, user_id=user.id)
    if trend is None:
        raise HTTPException(
            status_code=404, detail=f"No results found for {biomarker_id}."
        )
    return trend


@router.get("", response_model=list[ReportSummary])
def list_reports(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    reports = (
        db.query(Report)
        .filter(Report.user_id == user.id)
        .order_by(Report.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "report_date": r.report_date,
            "uploaded_at": r.uploaded_at,
            "result_count": len(r.results),
        }
        for r in reports
    ]


def _result_out(r: Result) -> dict:
    return {
        "biomarker_id": r.biomarker_id,
        "standard_name": r.standard_name,
        "original_name": r.original_name,
        "value": r.value,
        "unit": r.unit,
        "status": r.status,
        "ref_low": r.ref_low,
        "ref_high": r.ref_high,
        "flag": r.flag,
        "source": r.source,
        "method": r.method,
    }


@router.get("/compare", response_model=CompareResponse)
def compare_reports(
    a: int,
    b: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Side-by-side comparison of two of the patient's reports.

    Rows carry ``change`` markers: up / down / same / new / missing.
    Direction is never labeled as better or worse.
    """
    ra = _owned_report(db, a, user)
    rb = _owned_report(db, b, user)

    def side(r: Report) -> dict:
        return {"id": r.id, "filename": r.filename, "report_date": r.report_date}

    am = {r.biomarker_id: r for r in ra.results}
    bm = {r.biomarker_id: r for r in rb.results}
    rows = []
    for bid in sorted(
        set(am) | set(bm), key=lambda x: (am.get(x) or bm.get(x)).standard_name
    ):
        ra_r, rb_r = am.get(bid), bm.get(bid)
        std = (ra_r or rb_r).standard_name
        unit = (rb_r or ra_r).unit
        if ra_r is not None and rb_r is not None:
            if rb_r.value > ra_r.value:
                change = "up"
            elif rb_r.value < ra_r.value:
                change = "down"
            else:
                change = "same"
        elif rb_r is not None:
            change = "new"
        else:
            change = "missing"
        rows.append(
            {
                "biomarker_id": bid,
                "standard_name": std,
                "unit": unit,
                "a_value": ra_r.value if ra_r else None,
                "b_value": rb_r.value if rb_r else None,
                "a_status": ra_r.status if ra_r else None,
                "b_status": rb_r.status if rb_r else None,
                "change": change,
            }
        )
    return {"a": side(ra), "b": side(rb), "rows": rows}


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = _owned_report(db, report_id, user)
    results_out = [_result_out(r) for r in report.results]
    return {
        "id": report.id,
        "filename": report.filename,
        "report_date": report.report_date,
        "uploaded_at": report.uploaded_at,
        "results": results_out,
        "summary": analysis_service.summarize(results_out),
        "extraction_source": report.extraction_source or "rules",
    }
