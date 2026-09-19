"""PDF handling: save uploads to data/sample_reports/ and extract text with PyMuPDF.

OCR is optional: extract_text_ocr() is a stub hook marked OPTIONAL. When a page
yields no extractable text, we note it ("scanned page — OCR skipped") instead
of failing, so the rest of the pipeline still works on text-based PDFs.
"""
from pathlib import Path

import fitz  # PyMuPDF

from app.utils.paths import project_root

UPLOAD_DIR = project_root() / "data" / "sample_reports"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def save_upload(filename: str, file_obj) -> Path:
    """Persist an uploaded file, returning its final path (de-duplicated)."""
    safe_name = Path(filename).name  # strip any directory components
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"
    dest = UPLOAD_DIR / safe_name
    counter = 1
    while dest.exists():
        dest = UPLOAD_DIR / f"{dest.stem}_{counter}{dest.suffix}"
        counter += 1
    with open(dest, "wb") as out:
        out.write(file_obj.read())
    return dest


def extract_text(path: Path) -> tuple[str, int, list[str]]:
    """Extract text from every page.

    Returns (full_text, page_count, notes). Notes describe pages that look
    scanned so the caller can surface them to the user.
    """
    notes: list[str] = []
    pages_text: list[str] = []
    with fitz.open(path) as doc:
        page_count = len(doc)
        for i, page in enumerate(doc, start=1):
            text = page.get_text() or ""
            if not text.strip():
                text = extract_text_ocr(page) or ""
                if not text.strip():
                    notes.append(
                        f"Page {i}: scanned page — OCR skipped "
                        "(install Tesseract and enable the OCR hook)"
                    )
            pages_text.append(text)
    return "\n".join(pages_text), page_count, notes


def extract_text_ocr(page) -> str | None:
    """OPTIONAL OCR hook for scanned/image-only PDF pages.

    To enable: install Tesseract (https://github.com/tesseract-ocr/tesseract),
    then `pip install pytesseract`, and render the page to a pixmap here
    (e.g. ``pix = page.get_pixmap(dpi=200)`` -> PIL image ->
    ``pytesseract.image_to_string``).

    Returns the OCR'd text, or None when OCR is unavailable. The pipeline
    treats the page as scanned and moves on.
    """
    return None
