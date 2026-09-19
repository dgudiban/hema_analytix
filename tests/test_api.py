"""API tests: health, biomarker spec, upload -> analyze, and trends.

The upload tests build minimal real PDFs in memory (no fixture files) and
redirect uploads into a tmp dir so no test artifacts touch the repo.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import pdf_service

client = TestClient(app)


def make_pdf(lines: list[str]) -> bytes:
    """Build a minimal valid one-page PDF with the given text lines."""
    safe = [l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for l in lines]
    content = "BT /F1 18 Tf 50 750 Td\n" + "\n".join(
        f"({l}) Tj 0 -25 Td" for l in safe
    ) + "\nET"
    content_bytes = content.encode("latin-1")
    bodies = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        None,  # stream body, filled below
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(bodies, start=1):
        offsets.append(len(pdf))
        if i == 4:
            pdf += (
                f"4 0 obj\n<< /Length {len(content_bytes)} >>\nstream\n".encode("latin-1")
                + content_bytes
                + b"\nendstream\nendobj\n"
            )
        else:
            pdf += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref_pos = len(pdf)
    pdf += f"xref\n0 {len(bodies) + 1}\n".encode("latin-1")
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode("latin-1")
    pdf += (
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode("latin-1")
    return pdf


@pytest.fixture
def upload_dir(monkeypatch, tmp_path):
    """Keep uploaded PDFs out of the repo's data/ dir during tests."""
    monkeypatch.setattr(pdf_service, "UPLOAD_DIR", tmp_path)
    return tmp_path


def _upload_and_analyze(lines, filename="report.pdf"):
    up = client.post(
        "/api/reports/upload",
        files={"file": (filename, make_pdf(lines), "application/pdf")},
    )
    assert up.status_code == 200
    report_id = up.json()["report_id"]
    an = client.post(f"/api/reports/{report_id}/analyze")
    assert an.status_code == 200
    return up.json(), an.json()


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_biomarkers_endpoint():
    res = client.get("/api/biomarkers")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 45
    bm001 = next(b for b in data if b["biomarker_id"] == "BM001")
    assert bm001["standard_name"] == "Hemoglobin"
    assert bm001["common_aliases"] == ["Hb", "HGB", "Hemoglobin"]
    assert bm001["typical_units"] == "g/dL"
    assert bm001["supports_trend"] is True
    # No hard-coded reference ranges anywhere in the spec payload.
    assert all("ref_low" not in b and "ref_high" not in b for b in data)


def test_upload_rejects_non_pdf():
    res = client.post(
        "/api/reports/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400


def test_upload_analyze_flow(upload_dir):
    uploaded, analyzed = _upload_and_analyze(
        [
            "Report Date: 01/15/2026",
            "Hemoglobin 11.2 g/dL (12.0-15.5)",
            "WBC: 6,500 /uL  Ref 4,000-11,000",
            "Vitamin D 12 ng/mL",
        ]
    )
    assert uploaded["pages"] == 1
    assert uploaded["report_date"] == "2026-01-15"
    assert "Hemoglobin" in uploaded["text_preview"]

    by_id = {r["biomarker_id"]: r for r in analyzed["results"]}
    hgb = by_id["BM001"]
    assert hgb["value"] == pytest.approx(11.2)
    assert hgb["standard_name"] == "Hemoglobin"
    assert hgb["original_name"] == "Hemoglobin"
    assert hgb["ref_low"] == pytest.approx(12.0)
    assert hgb["ref_high"] == pytest.approx(15.5)
    assert hgb["status"] == "LOW"  # report range used, not a hard-coded one
    assert hgb["source"] == "reported"

    wbc = by_id["BM003"]
    assert wbc["value"] == 6500.0
    assert wbc["ref_low"] == pytest.approx(4000.0)
    assert wbc["status"] == "NORMAL"

    vitd = by_id["BM038"]
    assert vitd["status"] == "unknown"  # no range printed on the report

    # AI is optional: with no GROQ_API_KEY/GEMINI_API_KEY and no Ollama, it must be null.
    assert analyzed["ai_explanation"] is None
    assert "Hemoglobin" in analyzed["summary"]

    lst = client.get("/api/reports")
    assert lst.status_code == 200
    assert any(r["id"] == analyzed["report_id"] for r in lst.json())

    one = client.get(f"/api/reports/{analyzed['report_id']}")
    assert one.status_code == 200
    detail = one.json()
    assert detail["report_date"] == "2026-01-15"
    assert len(detail["results"]) >= 3
    assert all("biomarker_id" in r and "source" in r for r in detail["results"])


def test_upload_analyze_with_calculated(upload_dir):
    _, analyzed = _upload_and_analyze(
        [
            "Report Date: 02/01/2026",
            "Total Cholesterol 220 mg/dL (125-200)",
            "HDL 45 mg/dL (40-80)",
        ],
        filename="lipids.pdf",
    )
    by_id = {r["biomarker_id"]: r for r in analyzed["results"]}
    nh = by_id["BM031"]
    assert nh["value"] == pytest.approx(175.0)
    assert nh["source"] == "calculated"
    assert "BM027" in nh["method"]
    assert nh["status"] == "unknown"  # calculated rows have no report range


def test_trends_endpoint(upload_dir):
    _upload_and_analyze(
        ["Report Date: 01/15/2026", "Glucose 95 mg/dL (70-100)"],
        filename="g1.pdf",
    )
    _upload_and_analyze(
        ["Report Date: 06/15/2026", "Glucose 115 mg/dL (70-100)"],
        filename="g2.pdf",
    )
    res = client.get("/api/reports/trends/BM011")
    assert res.status_code == 200
    trend = res.json()
    assert trend["biomarker_id"] == "BM011"
    assert trend["standard_name"] == "Glucose"
    assert len(trend["points"]) == 2
    assert trend["points"][0]["report_date"] == "2026-01-15"
    assert trend["points"][1]["value"] == pytest.approx(115.0)
    assert trend["direction"] == "improving"


def test_trends_endpoint_no_data():
    assert client.get("/api/reports/trends/BM999").status_code == 404


def test_get_missing_report():
    assert client.get("/api/reports/999999").status_code == 404
    assert client.post("/api/reports/999999/analyze").status_code == 404
