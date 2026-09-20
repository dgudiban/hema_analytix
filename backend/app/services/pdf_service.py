"""Report ingestion: digital PDFs, scanned PDFs, and report images.

Pipeline::

    PDF with text layer  ->  PyMuPDF text extraction
    Scanned PDF page     ->  Tesseract OCR (page rendered at 200 DPI)
    Image file (JPG/PNG) ->  Tesseract OCR directly

OCR is best-effort: when the Tesseract binary or ``pytesseract`` is missing,
ingestion notes it and continues with whatever text was extractable, so a
missing OCR install can never break PDF uploads.
"""
from pathlib import Path
import shutil

import fitz  # PyMuPDF

from app.utils.paths import project_root

UPLOAD_DIR = project_root() / "data" / "sample_reports"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
PDF_SUFFIXES = {".pdf"}
ALLOWED_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES


def tesseract_available() -> bool:
    """True when both the Python binding and the Tesseract binary exist."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def ocr_pil_image(image) -> str | None:
    """OCR a PIL image. Returns the text, or None when OCR is unavailable."""
    if not tesseract_available():
        return None
    import pytesseract

    try:
        return pytesseract.image_to_string(image.convert("L")) or ""
    except Exception:
        return None


def extract_text_ocr(page) -> str | None:
    """OCR a single PyMuPDF page, rendered at 200 DPI."""
    try:
        pix = page.get_pixmap(dpi=200)
    except Exception:
        return None
    import io

    from PIL import Image

    try:
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return ocr_pil_image(img)
    except Exception:
        return None


def save_upload(filename: str, file_obj) -> Path:
    """Persist an uploaded PDF or image, returning its final path.

    Raises ValueError for unsupported file types.
    """
    safe_name = Path(filename).name  # strip any directory components
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(
            f"Unsupported file type {suffix or '(none)'} — "
            "upload a PDF or a JPG/PNG image."
        )
    dest = UPLOAD_DIR / safe_name
    counter = 1
    while dest.exists():
        dest = UPLOAD_DIR / f"{dest.stem}_{counter}{dest.suffix}"
        counter += 1
    with open(dest, "wb") as out:
        out.write(file_obj.read())
    return dest


def ingest(path: Path) -> dict:
    """Full ingestion of one uploaded file.

    Returns a dict with ``text``, ``pages``, ``notes`` (user-facing caveats),
    ``ocr_used`` (bool), and ``source_type`` ("pdf" | "scanned_pdf" | "image").
    """
    path = Path(path)
    notes: list[str] = []
    pages_text: list[str] = []
    ocr_used = False

    if path.suffix.lower() in IMAGE_SUFFIXES:
        text = _ocr_image_file(path)
        if text and text.strip():
            ocr_used = True
            pages_text.append(text)
        else:
            notes.append(
                "Image OCR produced no text — the image may be unreadable"
                + ("" if tesseract_available() else " (Tesseract not installed)")
                + "."
            )
        return {
            "text": "\n".join(pages_text),
            "pages": 1,
            "notes": notes,
            "ocr_used": ocr_used,
            "source_type": "image",
        }

    with fitz.open(path) as doc:
        page_count = len(doc)
        for i, page in enumerate(doc, start=1):
            text = page.get_text() or ""
            if not text.strip():
                ocr_text = extract_text_ocr(page) or ""
                if ocr_text.strip():
                    text = ocr_text
                    ocr_used = True
                else:
                    notes.append(
                        f"Page {i}: no extractable text"
                        + ("" if tesseract_available() else " and OCR unavailable")
                        + "."
                    )
            pages_text.append(text)
    return {
        "text": "\n".join(pages_text),
        "pages": page_count,
        "notes": notes,
        "ocr_used": ocr_used,
        "source_type": "scanned_pdf" if ocr_used else "pdf",
    }


def extract_text(path: Path) -> tuple[str, int, list[str]]:
    """Legacy 3-tuple wrapper (kept for the eval runner)."""
    ingested = ingest(path)
    return ingested["text"], ingested["pages"], ingested["notes"]


def _ocr_image_file(path: Path) -> str | None:
    from PIL import Image

    try:
        with Image.open(path) as img:
            return ocr_pil_image(img)
    except Exception:
        return None
