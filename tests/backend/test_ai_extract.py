"""Tests for AI-assisted extraction (ai_extract_service) and match_biomarker."""
import json
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
    {
        "biomarker_id": "BM020",
        "standard_name": "Vitamin D",
        "common_aliases": ["25-OH Vitamin D", "25 Hydroxy Vitamin D"],
        "typical_units": "ng/mL",
    },
    {
        "biomarker_id": "BM021",
        "standard_name": "HbA1c",
        "common_aliases": ["Hemoglobin A1c", "Glycated Hemoglobin"],
        "typical_units": "%",
    },
    {
        "biomarker_id": "BM022",
        "standard_name": "Vitamin B12",
        "common_aliases": ["Cobalamin"],
        "typical_units": "pg/mL",
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
    ) as fallback, patch.object(
        ai_extract_service.time, "sleep"
    ):
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


def test_bad_json_resamples_once_and_recovers():
    good = json.dumps(
        {
            "rows": [
                {
                    "test": "Hemoglobin",
                    "value": 14.5,
                    "unit": "g/dL",
                    "ref_low": 13.0,
                    "ref_high": 16.5,
                    "flag": None,
                }
            ]
        }
    )
    calls = {"n": 0}

    def fake_complete(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return ("not json at all", "openai/gpt-oss-20b")
        return (good, "openai/gpt-oss-20b")

    with patch.object(
        ai_extract_service.llm_client, "complete", side_effect=fake_complete
    ), patch.object(parse_service, "parse_text", return_value=[]):
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "ai"
    assert calls["n"] == 2  # one resample, no more
    assert out and out[0]["standard_name"] == "Hemoglobin"


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
    assert parse_service.match_biomarker("Calcium", SPEC)["biomarker_id"] == "BM010"
    assert parse_service.match_biomarker("", SPEC) is None
    # Printed variant with extra tokens still resolves to the right entry...
    assert (
        parse_service.match_biomarker("25(OH) Vitamin D", SPEC)["biomarker_id"]
        == "BM020"
    )
    # ...but a qualifier that marks a different analyte vetoes the merge.
    assert (
        parse_service.match_biomarker("Hemoglobin A1c", SPEC)["biomarker_id"]
        == "BM021"
    )
    assert (
        parse_service.match_biomarker("Glycated Hemoglobin", SPEC)["biomarker_id"]
        == "BM021"
    )


def test_value_with_comparison_operator_is_kept():
    chunk = "Vitamin B12\nL\npg/mL\n187 - 833\nCLIA\n< 148\n"
    rows = [
        {"test": "Vitamin B12", "value": "<148", "unit": "pg/mL",
         "ref_low": 187.0, "ref_high": 833.0, "flag": "L"},
    ]
    with patch.object(
        ai_extract_service.llm_client, "complete",
        return_value=_ai_json(rows),
    ), patch.object(ai_extract_service.time, "sleep"):
        out, source = ai_extract_service.extract(chunk, SPEC)
    assert source == "ai"
    assert out[0]["value"] == 148.0
    assert out[0]["flag"] == "Low"
    assert out[0]["standard_name"] == "Vitamin B12"


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


def test_unit_alias_normalization():
    row = ai_extract_service._validate_row(
        {"test": "Hemoglobin", "value": 14.5, "unit": "micro g/dL",
         "ref_low": 13.0, "ref_high": 16.5, "flag": None},
        "Hemoglobin micro g/dL 14.5",
        SPEC,
    )
    assert row["unit"] == "µg/dL"


def test_extract_json_handles_fences():
    raw = '```json\n{"rows": [{"test": "Hemoglobin", "value": 14.5}]}\n```'
    data = ai_extract_service._extract_json(raw)
    assert data["rows"][0]["value"] == 14.5


def test_chunk_retry_recovers_after_transient_failure():
    # First LLM call fails (e.g. TPM rate limit), second succeeds.
    rows = [
        {"test": "Hemoglobin", "value": 14.5, "unit": "g/dL",
         "ref_low": 13.0, "ref_high": 16.5, "flag": None},
    ]
    with patch.object(
        ai_extract_service.llm_client,
        "complete",
        side_effect=[(None, None), _ai_json(rows)],
    ) as complete, patch.object(
        ai_extract_service.time, "sleep"
    ) as sleep:
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "ai"
    assert out[0]["biomarker_id"] == "BM001"
    assert complete.call_count == 2
    # First retry backs off 20s; 20s + 40s fully clears the TPM window.
    sleep.assert_any_call(20)


def test_chunk_failure_is_exhausted_before_fallback():
    with patch.object(
        ai_extract_service.llm_client, "complete", return_value=(None, None)
    ) as complete, patch.object(
        ai_extract_service.time, "sleep"
    ) as sleep, patch.object(
        parse_service, "parse_text", return_value=[]
    ):
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    # 1 initial attempt + 2 short-backoff retries (20s + 40s clears the TPM window).
    assert complete.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [20, 40]
    assert source == "rules" and out == []


def _two_chunk_text():
    # >4500-char sections: chunk 0 is Hb-only, later chunks carry glucose.
    return (
        "Hemoglobin\ng/dL\n13.0 - 16.5\nColorimetric\n14.5\n" * 150
        + "Glucose\nmg/dL\n74 - 106\nFasting\n141\n" * 150
    )


def test_failed_chunk_falls_back_to_rule_parser_per_chunk():
    text = _two_chunk_text()
    hb_rows = [
        {"test": "Hemoglobin", "value": 14.5, "unit": "g/dL",
         "ref_low": 13.0, "ref_high": 16.5, "flag": None},
    ]
    glu_rule_row = {
        "biomarker_id": "BM099",
        "standard_name": "Glucose",
        "original_name": "Glucose",
        "value": 141.0,
        "unit": "mg/dL",
        "ref_low": 74.0,
        "ref_high": 106.0,
        "flag": None,
    }
    spec = SPEC + [
        {
            "biomarker_id": "BM099",
            "standard_name": "Glucose",
            "common_aliases": [],
            "typical_units": "mg/dL",
        }
    ]

    def fake_complete(prompt, system, max_tokens=None, model_order=None):
        # The Glucose chunk's report text carries "74 - 106"; fail it always.
        # (The canonical-names list also mentions Glucose, so match on the
        # report text, not the bare name.)
        if "74 - 106" in prompt:
            return None, None
        return _ai_json(hb_rows)

    def fake_parse(chunk_text, spec):
        if "74 - 106" in chunk_text:
            return [glu_rule_row]
        return []

    with patch.object(
        ai_extract_service.llm_client, "complete", side_effect=fake_complete
    ), patch.object(
        parse_service, "parse_text", side_effect=fake_parse
    ), patch.object(
        ai_extract_service.time, "sleep"
    ):
        out, source = ai_extract_service.extract(text, spec)
    assert source == "ai"  # AI did real work; one chunk covered by rules
    by_id = {r["biomarker_id"]: r for r in out}
    assert by_id["BM001"]["value"] == 14.5  # from the AI chunk
    assert by_id["BM099"]["value"] == 141.0  # from the rule fallback chunk


def test_backoff_stops_after_first_failed_chunk():
    text = "filler line\n" * 500  # exactly two chunks
    assert len(ai_extract_service._chunk_text(text)) == 2
    with patch.object(
        ai_extract_service.llm_client, "complete", return_value=(None, None)
    ) as complete, patch.object(
        ai_extract_service.time, "sleep"
    ), patch.object(
        parse_service, "parse_text", return_value=[]
    ):
        out, source = ai_extract_service.extract(text, SPEC)
    # First chunk: 1 attempt + 2 short-backoff retries.
    # Second chunk: single attempt, no backoff (backend already unreachable).
    assert complete.call_count == 4
    assert source == "rules" and out == []


def test_last_run_reports_chunk_outcome():
    rows = [
        {"test": "Hemoglobin", "value": 14.5, "unit": "g/dL",
         "ref_low": 13.0, "ref_high": 16.5, "flag": None},
    ]
    with patch.object(
        ai_extract_service.llm_client, "complete", return_value=_ai_json(rows)
    ):
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "ai"
    assert ai_extract_service.last_run == {
        "chunks": 1,
        "ai_chunks": 1,
        "failed_chunks": 0,
        "fail_reasons": [],
    }


def test_last_run_records_failure_reason(monkeypatch):
    monkeypatch.setattr(
        ai_extract_service.llm_client,
        "complete",
        lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        ai_extract_service.llm_client, "last_error", "groq:http_429"
    )
    with patch.object(ai_extract_service.time, "sleep"), patch.object(
        parse_service, "parse_text", return_value=[]
    ):
        out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "rules" and out == []
    assert ai_extract_service.last_run["chunks"] == 1
    assert ai_extract_service.last_run["ai_chunks"] == 0
    assert ai_extract_service.last_run["failed_chunks"] == 1
    assert ai_extract_service.last_run["fail_reasons"] == ["groq:http_429"]


def test_last_run_mixed_chunks(monkeypatch):
    # Chunk 0 transcribes via AI; chunk 1 is rate-limited and rule-parsed.
    text = _two_chunk_text()
    hb_rows = [
        {"test": "Hemoglobin", "value": 14.5, "unit": "g/dL",
         "ref_low": 13.0, "ref_high": 16.5, "flag": None},
    ]

    def fake_complete(prompt, system, max_tokens=None, model_order=None):
        if "74 - 106" in prompt:
            return None, None
        return _ai_json(hb_rows)

    monkeypatch.setattr(ai_extract_service.llm_client, "complete", fake_complete)
    monkeypatch.setattr(
        ai_extract_service.llm_client, "last_error", "groq:http_429"
    )
    with patch.object(ai_extract_service.time, "sleep"), patch.object(
        parse_service, "parse_text", return_value=[]
    ):
        out, source = ai_extract_service.extract(text, SPEC)
    assert source == "ai"
    assert ai_extract_service.last_run["chunks"] == 3
    assert ai_extract_service.last_run["ai_chunks"] == 1
    assert ai_extract_service.last_run["failed_chunks"] == 2
    assert ai_extract_service.last_run["fail_reasons"] == [
        "groq:http_429",
        "groq:http_429",
    ]


def test_last_run_notes_when_ai_disabled(monkeypatch):
    monkeypatch.setenv("AI_EXTRACTION", "off")
    out, source = ai_extract_service.extract(CHUNK, SPEC)
    assert source == "rules"
    assert ai_extract_service.last_run["note"] == "ai_disabled_or_empty"


def test_match_biomarker_test2_variants_against_real_spec():
    # Regression: test2.pdf prints "Fasting Blood Sugar" and "Direct LDL";
    # the matcher must resolve them, and must NOT merge ratio rows into LDL.
    from app.utils.spec import get_biomarkers

    real = get_biomarkers()
    assert parse_service.match_biomarker("Fasting Blood Sugar", real)[
        "standard_name"
    ] == "Glucose"
    assert parse_service.match_biomarker("Direct LDL", real)[
        "standard_name"
    ] == "LDL"
    assert parse_service.match_biomarker("LDL/HDL Ratio", real) is None
    assert parse_service.match_biomarker("CHOL/HDL Ratio", real) is None
    assert parse_service.match_biomarker("LDL", real)["standard_name"] == "LDL"
