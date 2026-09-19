"""Load the biomarker reference spec (biomarkers.json) into memory.

The JSON is regenerated from the xlsx source of truth by
``backend/app/utils/import_spec.py`` — never edit it by hand.
"""
import json
from functools import lru_cache

from app.utils.paths import project_root

SPEC_PATH = project_root() / "data" / "biomarkers" / "biomarkers.json"


@lru_cache(maxsize=1)
def load_spec() -> dict:
    with open(SPEC_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_biomarkers() -> list[dict]:
    return load_spec()["biomarkers"]


def get_disclaimer() -> str:
    return load_spec().get("disclaimer", "")


def get_biomarker(biomarker_id: str) -> dict | None:
    return next(
        (b for b in get_biomarkers() if b["biomarker_id"] == biomarker_id), None
    )
