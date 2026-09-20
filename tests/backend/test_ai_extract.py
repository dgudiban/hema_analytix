"""Tests for AI-assisted extraction (ai_extract_service) and match_biomarker."""
from unittest.mock import patch

import pytest

from app.services import ai_extract_service, parse_service

SPEC = [
    {
        "biomarker_id": "BM001",
        "standard_name": "Hemoglobin",
        "common_aliases": ["Hb"],
        "typical_units": "g/dL",
    },
    {
        "biomarker_id": "BM046",
        "standard_name": "Packed Cell Volume",
        "common_aliases": ["PCV", "Hematocrit", "HCT"],
        "typical_units": "%",
    },
    {
        "biomarker_id": "BM010",
        "standard_name": "Calcium",
        "common_aliases": [],
        "typical_units": "mg/dL",
    },
]

CHUNK = (
    "Hemoglobin\ng/dL\n13.0 - 16.5\nColorimetric\n14.5\n"
    "Hematocrit\n%\n40 - 49\nCalculated\n43.3\n"
)


def _ai_json(rows):
    import json

    return json.dumps({"rows": rows}), "openai/gpt-oss-120b"


def test_extract_uses_ai_rows_when_valid():
    rows = [
        {"test": "Hemoglobin", "value": 14.5, "unit": "g/dL",
         "ref_low": 13.0, "ref_high": 16.5, "flag": None},
        {"test": "Hematocrit", "value": 43.3, "unit": "%",
         "ref_low": 40.0, "ref_high": 49.0, "flag": None},
    ]
    with patch.object(
        ai_extract_service.llm_client, "complete", return_value=_ai_json(rows)
    ):
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "ai"
    by_id = {r["biomarker_id"]: r for r in out}
    assert by_id["BM001"]["value"] == 14.5
    assert by_id["BM001"]["ref_low"] == 13.0
    assert by_id["BM001"]["ref_high"] == 16.5
    assert by_id["BM001"]["unit"] == "g/dL"
    assert by_id["BM046"]["value"] == 43.3
    # canonical name from prompt maps via alias, original kept for traceability
    assert by_id["BM046"]["standard_name"] == "Packed Cell Volume"


def test_extract_drops_hallucinated_value_not_in_text():
    rows = [
        {"test": "Hemoglobin", "value": 99.9, "unit": "g/dL",
         "ref_low": 13.0, "ref_high": 16.5, "flag": None},
    ]
    with patch.object(
        ai_extract_service.llm_client, "complete", return_value=_ai_json(rows)
    ), patch.object(
        parse_service, "parse_text", return_value=[{"biomarker_id": "X"}]
    ) as fallback:
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "rules"  # AI row dropped -> empty -> rule fallback
    assert fallback.called


def test_extract_drops_name_not_in_spec():
    rows = [
        {"test": "Some Unknown Analyte", "value": 14.5, "unit": "g/dL",
         "ref_low": 13.0, "ref_high": 16.5, "flag": None},
    ]
    with patch.object(
        ai_extract_service.llm_client, "complete", return_value=_ai_json(rows)
    ), patch.object(
        parse_service, "parse_text", return_value=[{"biomarker_id": "X"}]
    ):
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "rules"


def test_extract_falls_back_when_no_llm_backend():
    with patch.object(
        ai_extract_service.llm_client, "complete", return_value=(None, None)
    ), patch.object(
        parse_service, "parse_text", return_value=[{"biomarker_id": "BM001"}]
    ) as fallback:
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "rules"
    assert out == [{"biomarker_id": "BM001"}]
    assert fallback.called


def test_extract_falls_back_on_bad_json():
    with patch.object(
        ai_extract_service.llm_client,
        "complete",
        return_value=("not json at all", "openai/gpt-oss-120b"),
    ), patch.object(
        parse_service, "parse_text", return_value=[]
    ):
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "rules" and out == []


def test_extract_respects_ai_extraction_off(monkeypatch):
    monkeypatch.setenv("AI_EXTRACTION", "off")
    with patch.object(
        ai_extract_service.llm_client, "complete"
    ) as complete, patch.object(
        parse_service, "parse_text", return_value=[]
    ):
        ai_extract_service.extract(CHUNK, SPEC)
    assert not complete.called


def test_match_biomarker_exact_and_alias():
    assert parse_service.match_biomarker("Hemoglobin", SPEC)["biomarker_id"] == "BM001"
    assert parse_service.match_biomarker("hb", SPEC)["biomarker_id"] == "BM001"
    assert parse_service.match_biomarker("Hematocrit", SPEC)["biomarker_id"] == "BM046"
    assert parse_service.match_biomarker("Hemoglobin (Hb)", SPEC)["biomarker_id"] == "BM001"


def test_match_biomarker_never_merges_subtype():
    # "Ionized Calcium" must NOT resolve to Calcium (BM010).
    assert parse_service.match_biomarker("Ionized Calcium", SPEC) is None
    assert parse_service.match_biomarker("Vitamin D", SPEC) is None
    assert parse_service.match_biomarker("", SPEC) is None


def test_flag_normalization():
    chunk = "Hemoglobin H\ng/dL\n13.0 - 16.5\n14.5\n"
    rows = [
        {"test": "Hemoglobin", "value": 14.5, "unit": "g/dL",
         "ref_low": 13.0, "ref_high": 16.5, "flag": "H"},
    ]
    with patch.object(
        ai_extract_service.llm_client, "complete", return_value=_ai_json(rows)
    ):
        out, _ = ai_extract_service.extract(chunk, SPEC)
    assert out[0]["flag"] == "High"


def test_extract_json_handles_fences():
    raw = '```json\n{"rows": [{"test": "Hemoglobin", "value": 14.5}]}\n```'
    data = ai_extract_service._extract_json(raw)
    assert data["rows"][0]["value"] == 14.5
