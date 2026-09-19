"""Regenerate data/biomarkers/biomarkers.json from the xlsx source of truth.

The Excel file ``BloodIQ_Biomarker_Specification_v2.xlsx`` is the authoritative
biomarker spec; this JSON is a build artifact. Re-run this script whenever the
spreadsheet changes:

    # from the project root
    python backend/app/utils/import_spec.py
    # or from inside backend/
    python -m app.utils.import_spec

No reference ranges are stored anywhere: the docs forbid universal hard-coded
ranges, so only the report-specific ranges printed on each lab report are used.
"""
import json
import sys
from pathlib import Path

import openpyxl

# Resolve paths from this file's location so the script runs from anywhere.
# utils/import_spec.py -> app -> backend -> project root (3 levels up).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
BIOMARKER_DIR = PROJECT_ROOT / "data" / "biomarkers"
XLSX_PATH = BIOMARKER_DIR / "BloodIQ_Biomarker_Specification_v2.xlsx"
JSON_PATH = BIOMARKER_DIR / "biomarkers.json"

DISCLAIMER = (
    "BloodIQ is educational and is not a substitute for professional "
    "medical advice. Always consult a qualified healthcare professional "
    "about your lab results."
)


def _split_aliases(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def import_spec(xlsx_path: Path = XLSX_PATH) -> dict:
    """Read the workbook and return the spec dict (also written to JSON)."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)

    ws = wb["Biomarkers"]
    biomarkers: list[dict] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:  # skip blank rows
            continue
        (
            biomarker_id,
            standard_name,
            category,
            common_aliases,
            typical_units,
            description,
            supports_trend,
            calculation_type,
            special_handling,
        ) = row[:9]
        biomarkers.append(
            {
                "biomarker_id": str(biomarker_id).strip(),
                "standard_name": str(standard_name).strip(),
                "category": str(category or "").strip(),
                "common_aliases": _split_aliases(common_aliases),
                "typical_units": str(typical_units or "").strip(),
                "description": str(description or "").strip(),
                "supports_trend": str(supports_trend or "").strip().lower() == "yes",
                "calculation_type": str(calculation_type or "").strip(),
                "special_handling": str(special_handling or "").strip(),
            }
        )

    notes_ws = wb["Implementation Notes"]
    implementation_notes: dict[str, str] = {}
    for row in notes_ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        implementation_notes[str(row[0]).strip()] = str(row[1] or "").strip()

    return {
        "disclaimer": DISCLAIMER,
        "implementation_notes": implementation_notes,
        "biomarkers": biomarkers,
    }


def main() -> None:
    if not XLSX_PATH.exists():
        print(f"ERROR: spec spreadsheet not found at {XLSX_PATH}", file=sys.stderr)
        sys.exit(1)
    spec = import_spec()
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(spec['biomarkers'])} biomarkers to {JSON_PATH}")


if __name__ == "__main__":
    main()
