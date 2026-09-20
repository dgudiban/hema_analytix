"""Report endpoints: upload, analyze, list, fetch, and trends."""
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.entities import Report, Result
from app.schemas.dto import (
    AnalyzeResponse,
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


@router.post("/upload", response_model=UploadResponse)
async def upload_report(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    saved_path = pdf_service.save_upload(file.filename, file.file)
    text, pages, notes = pdf_service.extract_text(saved_path)
    report_date = parse_report_date(text, fallback=date.today())

    report = Report(
        filename=saved_path.name, raw_text=text, report_date=report_date
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
    }


@router.post("/{report_id}/analyze", response_model=AnalyzeResponse)
def analyze_report(report_id: int, db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")

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
    }


# Registered BEFORE /{report_id} so the literal "trends" segment can never
# collide with a report id (report_id is int-typed anyway).
@router.get("/trends/{biomarker_id}", response_model=TrendResponse)
def get_trend(biomarker_id: str, db: Session = Depends(get_db)):
    trend = trend_service.get_trend(db, biomarker_id)
    if trend is None:
        raise HTTPException(
            status_code=404, detail=f"No results found for {biomarker_id}."
        )
    return trend


@router.get("", response_model=list[ReportSummary])
def list_reports(db: Session = Depends(get_db)):
    reports = db.query(Report).order_by(Report.id.desc()).all()
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
        "source": r.source,
        "method": r.method,
    }


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(report_id: int, db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return {
        "id": report.id,
        "filename": report.filename,
        "report_date": report.report_date,
        "uploaded_at": report.uploaded_at,
        "results": [_result_out(r) for r in report.results],
        "extraction_source": report.extraction_source or "rules",
    }
