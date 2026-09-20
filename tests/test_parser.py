"""Parser, normalization, and analysis tests on realistic report text.

Reference ranges come only from the report text itself; a missing range
means status "unknown" (no hard-coded fallbacks anywhere).
"""
import pytest

from app.services import analysis_service, normalize_service, parse_service
from app.utils.spec import get_biomarkers


@pytest.fixture(scope="module")
def spec():
    return get_biomarkers()


RANGES_TEXT = """
Report Date: 01/15/2026
COMPLETE BLOOD COUNT
Hemoglobin 11.2 g/dL (12.0-15.5)
RBC Count 5.1 million/µL (4.5-5.9)
WBC: 6,500 /uL  Ref 4,000-11,000
Platelet Count 210,000 /µL (150,000-450,000)
LIVER
ALT 42 U/L (7-56)
KIDNEY
eGFR 95 mL/min/1.73 m2 > 60
LIPIDS
Cholesterol 215 mg/dL (<200)
VITAMINS
Vitamin D 12 ng/mL
"""


@pytest.fixture(scope="module")
def parsed(spec):
    return parse_service.parse_text(RANGES_TEXT, spec)


def _by_id(parsed, biomarker_id):
    return next(p for p in parsed if p["biomarker_id"] == biomarker_id)


def test_spec_entries(spec):
    ids = [b["biomarker_id"] for b in spec]
    assert len(spec) == 46
    assert ids[0] == "BM001" and ids[-1] == "BM046"
    # No hard-coded reference-range keys anywhere in the spec entries.
    assert all("ref_low" not in b and "ref_high" not in b for b in spec)
    # No hard-coded reference-range keys anywhere in the spec entries.
    assert all("ref_low" not in b and "ref_high" not in b for b in spec)


def test_parenthesized_ranges(parsed):
    hgb = _by_id(parsed, "BM001")
    assert hgb["value"] == pytest.approx(11.2)
    assert hgb["ref_low"] == pytest.approx(12.0)
    assert hgb["ref_high"] == pytest.approx(15.5)
    assert hgb["standard_name"] == "Hemoglobin"
    assert hgb["original_name"] == "Hemoglobin"
    assert hgb["unit"] == "g/dL"


def test_ref_prefixed_range_with_thousands_commas(parsed):
    wbc = _by_id(parsed, "BM003")
    assert wbc["value"] == 6500.0
    assert wbc["ref_low"] == pytest.approx(4000.0)
    assert wbc["ref_high"] == pytest.approx(11000.0)
    assert wbc["unit"] == "/uL"


def test_thousands_commas_in_value_and_range(parsed):
    plt = _by_id(parsed, "BM008")
    assert plt["value"] == 210000.0
    assert plt["ref_low"] == pytest.approx(150000.0)
    assert plt["ref_high"] == pytest.approx(450000.0)


def test_bare_integer_range(parsed):
    alt = _by_id(parsed, "BM021")
    assert (alt["ref_low"], alt["ref_high"]) == (pytest.approx(7.0), pytest.approx(56.0))


def test_open_ended_ranges(parsed):
    egfr = _by_id(parsed, "BM045")
    assert egfr["ref_low"] == pytest.approx(60.0)
    assert egfr["ref_high"] is None
    chol = _by_id(parsed, "BM027")
    assert chol["ref_low"] is None
    assert chol["ref_high"] == pytest.approx(200.0)


def test_open_ended_value_form(spec):
    parsed = parse_service.parse_text("eGFR > 60", spec)
    assert len(parsed) == 1
    assert parsed[0]["biomarker_id"] == "BM045"
    assert parsed[0]["value"] == pytest.approx(60.0)
    assert parsed[0]["ref_low"] == pytest.approx(60.0)
    assert parsed[0]["ref_high"] is None
    parsed = parse_service.parse_text("Cholesterol < 200", spec)
    assert parsed[0]["biomarker_id"] == "BM027"
    assert parsed[0]["ref_high"] == pytest.approx(200.0)


def test_status_rules(spec):
    analyzed = analysis_service.analyze(
        normalize_service.normalize(parse_service.parse_text(RANGES_TEXT, spec))
    )
    by_id = {r["biomarker_id"]: r for r in analyzed}
    assert by_id["BM001"]["status"] == "LOW"      # 11.2 < 12.0
    assert by_id["BM027"]["status"] == "HIGH"     # 215 > 200
    assert by_id["BM021"]["status"] == "NORMAL"   # 42 in 7-56
    assert by_id["BM045"]["status"] == "NORMAL"   # 95 not < 60 (one-sided low)
    assert by_id["BM038"]["status"] == "unknown"  # Vitamin D: no range printed


def test_status_unknown_without_range(spec):
    parsed = parse_service.parse_text("Hemoglobin 13.2 g/dL", spec)
    assert parsed[0]["ref_low"] is None and parsed[0]["ref_high"] is None
    analyzed = analysis_service.analyze(normalize_service.normalize(parsed))
    assert analyzed[0]["status"] == "unknown"


def test_alias_mapping_and_original_name(spec):
    parsed = parse_service.parse_text("HGB 13.8 g/dL (12.0-16.0)", spec)
    assert len(parsed) == 1
    assert parsed[0]["biomarker_id"] == "BM001"
    assert parsed[0]["standard_name"] == "Hemoglobin"
    assert parsed[0]["original_name"] == "HGB"  # as written in the report


def test_longest_alias_wins(spec):
    parsed = parse_service.parse_text("Total Cholesterol 185 mg/dL", spec)
    assert len(parsed) == 1
    assert parsed[0]["biomarker_id"] == "BM027"


def test_no_partial_alias_match(spec):
    parsed = parse_service.parse_text("HbA1c 5.2 %", spec)
    assert [p["biomarker_id"] for p in parsed] == ["BM012"]


def test_no_subtype_merges(spec):
    text = "\n".join(
        [
            "RDW-CV 12.5 %",
            "RDW-SD 42 fL",
            "hs-CRP 1.5 mg/L",
            "C-Reactive Protein 0.8 mg/L",
            "Ionized Calcium 4.7 mg/dL",
            "Calcium 9.4 mg/dL",
            "RBC Folate 400 ng/mL",
            "Serum Folate 8 ng/mL",
            "1,25-Dihydroxy Vitamin D 45 pg/mL",
            "Vitamin D 32 ng/mL",
        ]
    )
    parsed = parse_service.parse_text(text, spec)
    by_id = {p["biomarker_id"]: p for p in parsed}
    # RDW-CV maps to BM009; RDW-SD must not merge into it.
    assert by_id["BM009"]["original_name"] == "RDW-CV"
    assert by_id["BM009"]["value"] == pytest.approx(12.5)
    # Standard CRP maps to BM041; hs-CRP must not merge into it.
    assert by_id["BM041"]["original_name"] == "C-Reactive Protein"
    assert by_id["BM041"]["value"] == pytest.approx(0.8)
    # Total calcium maps to BM019; ionized calcium must not merge.
    assert by_id["BM019"]["original_name"] == "Calcium"
    # Serum folate maps to BM040; RBC folate must not merge.
    assert by_id["BM040"]["original_name"] == "Serum Folate"
    # Vitamin D maps to BM038; the 1,25 metabolite must not merge.
    assert by_id["BM038"]["original_name"] == "Vitamin D"


def test_source_is_reported(spec):
    parsed = parse_service.parse_text("Hemoglobin 13.2 g/dL (12-16)", spec)
    normed = normalize_service.normalize(parsed)
    assert all(r["source"] == "reported" for r in normed)
    assert all(r["method"] is None for r in normed)


def test_non_hdl_calculated(spec):
    text = "Total Cholesterol 220 mg/dL (125-200)\nHDL 45 mg/dL (40-80)"
    parsed = parse_service.parse_text(text, spec)
    out = normalize_service.add_calculated(normalize_service.normalize(parsed))
    nh = next(r for r in out if r["biomarker_id"] == "BM031")
    assert nh["value"] == pytest.approx(175.0)
    assert nh["unit"] == "mg/dL"
    assert nh["source"] == "calculated"
    assert "BM027" in nh["method"] and "BM029" in nh["method"]
    assert nh["ref_low"] is None and nh["ref_high"] is None


def test_non_hdl_reported_wins(spec):
    text = "Total Cholesterol 220 mg/dL\nHDL 45 mg/dL\nNon-HDL-C 160 mg/dL"
    parsed = parse_service.parse_text(text, spec)
    out = normalize_service.add_calculated(normalize_service.normalize(parsed))
    nh = [r for r in out if r["biomarker_id"] == "BM031"]
    assert len(nh) == 1
    assert nh[0]["value"] == pytest.approx(160.0)
    assert nh[0]["source"] == "reported"


def test_tsat_calculated(spec):
    text = "Iron 90 \u00b5g/dL (50-170)\nTIBC 300 \u00b5g/dL (250-450)"
    parsed = parse_service.parse_text(text, spec)
    out = normalize_service.add_calculated(normalize_service.normalize(parsed))
    tsat = next(r for r in out if r["biomarker_id"] == "BM037")
    assert tsat["value"] == pytest.approx(30.0)
    assert tsat["unit"] == "%"
    assert tsat["source"] == "calculated"
    assert "BM035" in tsat["method"] and "BM036" in tsat["method"]


def test_tsat_reported_wins(spec):
    text = "Iron 90 \u00b5g/dL\nTIBC 300 \u00b5g/dL\nTSAT 28 %"
    parsed = parse_service.parse_text(text, spec)
    out = normalize_service.add_calculated(normalize_service.normalize(parsed))
    tsat = [r for r in out if r["biomarker_id"] == "BM037"]
    assert len(tsat) == 1
    assert tsat[0]["value"] == pytest.approx(28.0)
    assert tsat[0]["source"] == "reported"


def test_calculated_skipped_when_units_incompatible(spec):
    text = "Total Cholesterol 5.6 mmol/L\nHDL 45 mg/dL"
    parsed = parse_service.parse_text(text, spec)
    out = normalize_service.add_calculated(normalize_service.normalize(parsed))
    assert not any(r["biomarker_id"] == "BM031" for r in out)


def test_summary_text(spec):
    analyzed = analysis_service.analyze(
        normalize_service.normalize(
            parse_service.parse_text(
                "Vitamin D 12 ng/mL\nLDL 160 mg/dL (0-100)\nHemoglobin 14.0 g/dL",
                spec,
            )
        )
    )
    summary = analysis_service.summarize(analyzed)
    assert "Vitamin D" in summary
    assert "LDL" in summary
    assert "1 normal" not in summary  # hemoglobin has no range -> unknown
    assert "without a reference range" in summary


def test_empty_text(spec):
    assert parse_service.parse_text("", spec) == []
    assert analysis_service.summarize([]) == "Analyzed 0 biomarker(s): 0 normal."


def test_parenthetical_alias_and_bare_range(spec):
    # Drlogy-style line: "Hemoglobin (Hb) 12.5 Low 13.0 - 17.0 g/dL"
    parsed = parse_service.parse_text(
        "Hemoglobin (Hb) 12.5 Low 13.0 - 17.0 g/dL", spec
    )
    assert len(parsed) == 1
    hgb = parsed[0]
    assert hgb["biomarker_id"] == "BM001"
    assert hgb["value"] == pytest.approx(12.5)
    assert hgb["ref_low"] == pytest.approx(13.0)
    assert hgb["ref_high"] == pytest.approx(17.0)
    assert hgb["flag"] == "Low"


def test_bare_range_no_spaces(spec):
    parsed = parse_service.parse_text(
        "Total WBC count 9000 4000-11000 cumm", spec
    )
    wbc = next(p for p in parsed if p["biomarker_id"] == "BM003")
    assert wbc["value"] == pytest.approx(9000.0)
    assert wbc["ref_low"] == pytest.approx(4000.0)
    assert wbc["ref_high"] == pytest.approx(11000.0)


def test_pcv_extraction_and_high_status(spec):
    parsed = parse_service.parse_text(
        "Packed Cell Volume (PCV) 57.5 High 40 - 50 %", spec
    )
    pcv = next(p for p in parsed if p["biomarker_id"] == "BM046")
    assert pcv["value"] == pytest.approx(57.5)
    assert pcv["ref_low"] == pytest.approx(40.0)
    assert pcv["ref_high"] == pytest.approx(50.0)
    assert pcv["flag"] == "High"
    analyzed = analysis_service.analyze(
        normalize_service.normalize(parsed)
    )
    pcv_a = next(r for r in analyzed if r["biomarker_id"] == "BM046")
    assert pcv_a["status"] == "HIGH"


def test_flag_fallback_status_without_range(spec):
    # No range printed: the lab's own flag is transcribed, not "unknown".
    analyzed = analysis_service.analyze(
        normalize_service.normalize(
            parse_service.parse_text("Hemoglobin 12.5 g/dL Low", spec)
        )
    )
    assert analyzed[0]["status"] == "LOW"
    assert analyzed[0]["flag"] == "Low"


def test_extract_interpretation():
    text = "Hemoglobin 12.5 g/dL\nInterpretation: Further confirm for Anemia\nEnd of Report"
    assert parse_service.extract_interpretation(text) == "Further confirm for Anemia"
    assert parse_service.extract_interpretation("no interpretation here") is None


def test_summary_findings_format(spec):
    analyzed = analysis_service.analyze(
        normalize_service.normalize(
            parse_service.parse_text(
                "Hemoglobin (Hb) 12.5 Low 13.0 - 17.0 g/dL\n"
                "Packed Cell Volume (PCV) 57.5 High 40 - 50 %\n"
                "WBC 6500 /uL 4000-11000",
                spec,
            )
        )
    )
    summary = analysis_service.summarize(
        analyzed, interpretation="Further confirm for Anemia"
    )
    assert "2 outside reference range" in summary
    assert "Hemoglobin LOW at 12.5 g/dL (ref 13–17, lab flag: Low)" in summary
    assert "Packed Cell Volume HIGH at 57.5 % (ref 40–50, lab flag: High)" in summary
    assert "Lab interpretation: Further confirm for Anemia." in summary
    assert "not a diagnosis" in summary
