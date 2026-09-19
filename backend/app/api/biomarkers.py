"""Reference biomarker spec endpoint (read-only).

The spec served here is regenerated from the xlsx source of truth by
``backend/app/utils/import_spec.py``.
"""
from fastapi import APIRouter

from app.schemas.dto import BiomarkerSpec
from app.utils.spec import get_biomarkers

router = APIRouter()


@router.get("", response_model=list[BiomarkerSpec])
def list_biomarkers():
    return get_biomarkers()
