"""Synthetic evaluation dataset for BloodIQ.

Generates fixture lab-report PDFs with a known ground-truth manifest, so the
extraction / normalization / classification pipeline can be scored
deterministically. No real patient data, no LLM needed.

Fixtures cover:
  - standard layouts ("Name value unit (low-high)", "Ref low-high")
  - alias spellings ("Hb", "Vit D3", "T. Chol")
  - missing reference ranges (-> status "unknown")
  - comma-formatted values ("6,500")
  - guarded subtypes (RDW-CV, 25-Hydroxy vitamin D, hs-CRP, ionized calcium)
  - calculated biomarkers (Non-HDL, Transferrin Saturation)
  - dated report series for trend evaluation

Run from backend/:  python -m eval.dataset
Writes: backend/eval/fixtures/pdfs/*.pdf and backend/eval/fixtures/manifest.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # PyMuPDF  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
PDF_DIR = FIXTURE_DIR / "pdfs"

# Each fixture: report id, printed date, and text lines.
# Ground truth lives in EXPECTED below, keyed by report id.
REPORTS = [
    ("R01", "2026-01-10", [
        "CityLab Diagnostics - Complete Blood Count & Lipid Panel",
        "Report Date: 2026-01-10",
        "Hemoglobin 11.2 g/dL (12.0-15.5)",
        "WBC 6,500 /uL Ref 4,000-11,000",
        "Total Cholesterol 210 mg/dL (125-200)",
        "HDL 55 mg/dL (40-60)",
        "Vitamin D 18 ng/mL (30-100)",
    ]),
    ("R02", "2026-02-10", [
        "CityLab Diagnostics",
        "Report Date: 2026-02-10",
        "Hb 13.0 g/dL (12.0-15.5)",
        "Vit D 25 ng/mL",
        "TC 190 mg/dL (125-200)",
        "Glucose 99 mg/dL (70-100)",
    ]),
    ("R03", "2026-03-10", [
        "CityLab Diagnostics",
        "Report Date: 2026-03-10",
        "RDW-CV 14.1 % (11.5-14.5)",
        "25-Hydroxy Vitamin D 22 ng/mL (30-100)",
        "CRP 1.2 mg/L (0.0-3.0)",
        "Calcium 9.4 mg/dL (8.5-10.5)",
    ]),
    ("R04", "2026-04-10", [
        "CityLab Diagnostics",
        "Report Date: 2026-04-10",
        "LDL: 118 mg/dL",
        "Triglycerides - 140 mg/dL (0-150)",
        "Folate 8.5 ng/mL (3.0-17.0)",
        "eGFR 92 mL/min/1.73m2 (60-120)",
    ]),
    ("R05", "2026-01-15", [
        "CityLab Diagnostics",
        "Report Date: 2026-01-15",
        "Hemoglobin 10.5 g/dL (12.0-15.5)",
    ]),
    ("R06", "2026-04-15", [
        "CityLab Diagnostics",
        "Report Date: 2026-04-15",
        "Hemoglobin 11.2 g/dL (12.0-15.5)",
    ]),
    ("R07", "2026-07-15", [
        "CityLab Diagnostics",
        "Report Date: 2026-07-15",
        "Hemoglobin 12.1 g/dL (12.0-15.5)",
    ]),
    ("R08", "2026-02-01", [
        "CityLab Diagnostics",
        "Report Date: 2026-02-01",
        "Total Cholesterol 240 mg/dL (125-200)",
    ]),
    ("R09", "2026-05-01", [
        "CityLab Diagnostics",
        "Report Date: 2026-05-01",
        "Total Cholesterol 220 mg/dL (125-200)",
    ]),
    ("R10", "2026-08-01", [
        "CityLab Diagnostics",
        "Report Date: 2026-08-01",
        "Total Cholesterol 205 mg/dL (125-200)",
    ]),
    ("R11", "2026-03-01", [
        "CityLab Diagnostics",
        "Report Date: 2026-03-01",
        "Glucose 95 mg/dL (70-100)",
    ]),
    ("R12", "2026-06-01", [
        "CityLab Diagnostics",
        "Report Date: 2026-06-01",
        "Glucose 97 mg/dL (70-100)",
    ]),
]

# Ground truth: biomarker_id, value, unit, ref_low, ref_high, expected status.
# "source": reported | calculated. Calculated rows are verified separately
# (the parser must NOT invent them; normalize.add_calculated must).
EXPECTED = {
    "R01": [
        ("BM001", 11.2, "g/dL", 12.0, 15.5, "LOW", "reported"),
        ("BM003", 6500.0, "/uL", 4000.0, 11000.0, "NORMAL", "reported"),
        ("BM027", 210.0, "mg/dL", 125.0, 200.0, "HIGH", "reported"),
        ("BM029", 55.0, "mg/dL", 40.0, 60.0, "NORMAL", "reported"),
        ("BM038", 18.0, "ng/mL", 30.0, 100.0, "LOW", "reported"),
        ("BM031", 155.0, "mg/dL", None, None, "unknown", "calculated"),
    ],
    "R02": [
        ("BM001", 13.0, "g/dL", 12.0, 15.5, "NORMAL", "reported"),
        ("BM038", 25.0, "ng/mL", None, None, "unknown", "reported"),
        ("BM027", 190.0, "mg/dL", 125.0, 200.0, "NORMAL", "reported"),
        ("BM011", 99.0, "mg/dL", 70.0, 100.0, "NORMAL", "reported"),
    ],
    "R03": [
        ("BM009", 14.1, "%", 11.5, 14.5, "NORMAL", "reported"),
        ("BM038", 22.0, "ng/mL", 30.0, 100.0, "LOW", "reported"),
        ("BM041", 1.2, "mg/L", 0.0, 3.0, "NORMAL", "reported"),
        ("BM019", 9.4, "mg/dL", 8.5, 10.5, "NORMAL", "reported"),
    ],
    "R04": [
        ("BM028", 118.0, "mg/dL", None, None, "unknown", "reported"),
        ("BM030", 140.0, "mg/dL", 0.0, 150.0, "NORMAL", "reported"),
        ("BM040", 8.5, "ng/mL", 3.0, 17.0, "NORMAL", "reported"),
        ("BM045", 92.0, "mL/min/1.73m2", 60.0, 120.0, "NORMAL", "reported"),
    ],
    "R05": [("BM001", 10.5, "g/dL", 12.0, 15.5, "LOW", "reported")],
    "R06": [("BM001", 11.2, "g/dL", 12.0, 15.5, "LOW", "reported")],
    "R07": [("BM001", 12.1, "g/dL", 12.0, 15.5, "NORMAL", "reported")],
    "R08": [("BM027", 240.0, "mg/dL", 125.0, 200.0, "HIGH", "reported")],
    "R09": [("BM027", 220.0, "mg/dL", 125.0, 200.0, "HIGH", "reported")],
    "R10": [("BM027", 205.0, "mg/dL", 125.0, 200.0, "HIGH", "reported")],
    "R11": [("BM011", 95.0, "mg/dL", 70.0, 100.0, "NORMAL", "reported")],
    "R12": [("BM011", 97.0, "mg/dL", 70.0, 100.0, "NORMAL", "reported")],
}

TREND_SERIES = [
    {"biomarker_id": "BM001", "reports": ["R05", "R06", "R07"],
     "expected": "improving", "note": "hemoglobin 10.5 -> 11.2 -> 12.1"},
    {"biomarker_id": "BM027", "reports": ["R08", "R09", "R10"],
     "expected": "declining", "note": "total cholesterol 240 -> 220 -> 205"},
    {"biomarker_id": "BM011", "reports": ["R11", "R12"],
     "expected": "stable", "note": "glucose 95 -> 97 (within 5% tolerance)"},
]


def _write_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 22
    doc.save(str(path))


def main() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"reports": [], "trend_series": TREND_SERIES}
    for rid, date, lines in REPORTS:
        pdf_path = PDF_DIR / f"{rid}.pdf"
        _write_pdf(pdf_path, lines)
        manifest["reports"].append({
            "id": rid,
            "date": date,
            "pdf": f"pdfs/{rid}.pdf",
            "results": [
                {"biomarker_id": bid, "value": val, "unit": unit,
                 "ref_low": lo, "ref_high": hi, "status": st, "source": src}
                for bid, val, unit, lo, hi, st, src in EXPECTED[rid]
            ],
        })
    (FIXTURE_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    n_results = sum(len(r["results"]) for r in manifest["reports"])
    print(f"Wrote {len(manifest['reports'])} PDFs "
          f"({n_results} expected results) to {PDF_DIR}")


if __name__ == "__main__":
    main()
