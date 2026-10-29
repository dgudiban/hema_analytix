"""AI explanation format tests: friendly prose, never a table, and the
required closing line is always present."""

from app.services import ai_service


def _results():
    return [
        {
            "standard_name": "Vitamin B12",
            "original_name": "Vitamin B12",
            "value": 148,
            "unit": "pg/mL",
            "ref_low": None,
            "ref_high": None,
            "status": "LOW",
            "flag": "L",
        },
        {
            "standard_name": "Hemoglobin",
            "original_name": "Hemoglobin",
            "value": 14.5,
            "unit": "g/dL",
            "ref_low": 12.0,
            "ref_high": 15.5,
            "status": "NORMAL",
        },
    ]


def test_explain_prompt_forbids_tables_and_asks_plain_language():
    prompt = ai_service._build_prompt(_results(), "Analyzed 2 biomarker(s): 1 normal")
    assert "Do NOT use a table" in prompt
    assert "non-medical person can understand" in prompt
    assert "What needs a closer look" in prompt
    assert "What's looking good" in prompt
    assert "What to do next" in prompt
    assert "doesn't print a range" in prompt
    assert ai_service.CLOSING_LINE in prompt


def test_ensure_closing_line_appends_when_missing():
    out = ai_service.ensure_closing_line("Some friendly explanation.")
    assert out.endswith(ai_service.CLOSING_LINE)


def test_ensure_closing_line_no_duplicate():
    text = "Some friendly explanation.\n\n" + ai_service.CLOSING_LINE
    assert ai_service.ensure_closing_line(text) == text


def test_ensure_closing_line_none_stays_none():
    assert ai_service.ensure_closing_line(None) is None
