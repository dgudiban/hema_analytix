"""Ingestion tests: image upload + OCR, scanned-PDF OCR fallback, type gating.

Tests that need the real Tesseract binary skip gracefully when it is absent
(the pipeline itself degrades the same way in production).
"""
import shutil

import fitz
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import pdf_service
from conftest import make_auth_headers

client = TestClient(app)

TESSERACT = pdf_service.tesseract_available()
needs_tesseract = pytest.mark.skipif(
    not TESSERACT, reason="Tesseract binary or pytesseract missing"
)


@pytest.fixture(autouse=True)
def _no_ai_extraction(monkeypatch):
    monkeypatch.setenv("AI_EXTRACTION", "off")


@pytest.fixture()
def upload_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf_service, "UPLOAD_DIR", tmp_path)
    return tmp_path


def _headers():
    return make_auth_headers(client)


def _blank_pdf(path):
    doc = fitz.Document()
    doc.new_page()
    doc.save(path)
    doc.close()


# ---- unit: file gating ----


def test_save_upload_rejects_unsupported_type(tmp_path):
    import io

    with pytest.raises(ValueError, match="Unsupported file type"):
        pdf_service.save_upload("notes.txt", io.BytesIO(b"hello"))
    # Supported types pass the gate.
    p = pdf_service.save_upload("scan.PNG", io.BytesIO(b"fake-bytes"))
    assert p.suffix == ".PNG"


def test_upload_endpoint_rejects_gif(upload_dir):
    res = client.post(
        "/api/reports/upload",
        files={"file": ("anim.gif", b"GIF89a", "image/gif")},
        headers=_headers(),
    )
    assert res.status_code == 400


# ---- unit: scanned-PDF OCR fallback (hook mocked, no binary needed) ----


def test_ingest_scanned_pdf_uses_ocr_text(monkeypatch, tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    _blank_pdf(pdf_path)
    monkeypatch.setattr(
        pdf_service, "extract_text_ocr", lambda page: "Hemoglobin 10 g/dL (12-15)"
    )
    out = pdf_service.ingest(pdf_path)
    assert out["ocr_used"] is True
    assert out["source_type"] == "scanned_pdf"
    assert "Hemoglobin" in out["text"]


def test_ingest_scanned_pdf_without_ocr_notes_it(monkeypatch, tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    _blank_pdf(pdf_path)
    monkeypatch.setattr(pdf_service, "extract_text_ocr", lambda page: None)
    out = pdf_service.ingest(pdf_path)
    assert out["ocr_used"] is False
    assert out["source_type"] == "pdf"
    assert any("Page 1" in n for n in out["notes"])


def test_ingest_digital_pdf_needs_no_ocr(tmp_path):
    pytest.importorskip("test_api")
    from test_api import make_pdf

    pdf_path = tmp_path / "digital.pdf"
    pdf_path.write_bytes(make_pdf(["Hemoglobin 11.2 g/dL (12.0-15.5)"]))
    out = pdf_service.ingest(pdf_path)
    assert out["ocr_used"] is False
    assert out["source_type"] == "pdf"
    assert "Hemoglobin" in out["text"]


# ---- end to end: real OCR on a generated report image ----


def _render_report_image(path, lines):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 60 + 50 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    try:
        from PIL import ImageFont

        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = None
    for i, line in enumerate(lines):
        draw.text((30, 20 + 50 * i), line, fill="black", font=font)
    img.save(path)


@needs_tesseract
def test_image_upload_end_to_end(upload_dir, tmp_path):
    img_path = tmp_path / "report.png"
    _render_report_image(
        img_path,
        ["Report Date: 01/15/2026", "Hemoglobin 11.2 g/dL (12.0-15.5)"],
    )
    headers = _headers()
    up = client.post(
        "/api/reports/upload",
        files={"file": ("report.png", img_path.read_bytes(), "image/png")},
        headers=headers,
    )
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["source_type"] == "image"
    assert "Hemoglobin" in body["text_preview"], body["text_preview"][:200]

    an = client.post(f"/api/reports/{body['report_id']}/analyze", headers=headers)
    assert an.status_code == 200
    by_id = {r["biomarker_id"]: r for r in an.json()["results"]}
    assert by_id["BM001"]["value"] == pytest.approx(11.2)
    assert by_id["BM001"]["status"] == "LOW"


@needs_tesseract
def test_ocr_image_file_reads_text(tmp_path):
    img_path = tmp_path / "lab.jpg"
    _render_report_image(img_path, ["Vitamin D 12 ng/mL"])
    text = pdf_service._ocr_image_file(img_path)
    assert text is not None
    assert "Vitamin" in text or "12" in text, text[:200]


@needs_tesseract
def test_tesseract_binary_present():
    assert shutil.which("tesseract") is not None
