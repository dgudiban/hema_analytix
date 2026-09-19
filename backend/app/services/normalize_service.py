"""Biomarker normalization.

The alias -> biomarker_id mapping happens in ``parse_service`` strictly via
each spec entry's ``standard_name`` + ``common_aliases`` lists, so subtypes
that are not aliases (RDW-SD vs RDW-CV, hs-CRP vs CRP, ionized vs total
calcium, serum vs RBC folate, vitamin D metabolites) never merge into the
wrong entry. This module stamps every result with its ``source`` and derives
the calculated biomarkers (Non-HDL cholesterol, transferrin saturation) when
their inputs are present with compatible units.
"""
from app.utils.units import normalize_unit


def normalize(matches: list[dict]) -> list[dict]:
    """Tag parsed matches as directly reported results."""
    return [{**m, "source": "reported", "method": None} for m in matches]


def _first(results: list[dict], biomarker_id: str) -> dict | None:
    return next((r for r in results if r["biomarker_id"] == biomarker_id), None)


def _compatible(a: dict, b: dict) -> bool:
    return normalize_unit(a["unit"]) == normalize_unit(b["unit"])


def add_calculated(results: list[dict]) -> list[dict]:
    """Append calculated biomarkers when their inputs are available.

    - Non-HDL cholesterol (BM031) = total cholesterol (BM027) − HDL (BM029)
    - Transferrin saturation (BM037) = serum iron (BM035) / TIBC (BM036) × 100

    A directly reported value always wins; calculated rows carry
    ``source="calculated"`` plus a ``method`` describing the derivation.
    """
    results = list(results)

    # Non-HDL cholesterol (BM031).
    if _first(results, "BM031") is None:
        tc, hdl = _first(results, "BM027"), _first(results, "BM029")
        if tc is not None and hdl is not None and _compatible(tc, hdl):
            results.append(
                {
                    "biomarker_id": "BM031",
                    "standard_name": "Non-HDL Cholesterol",
                    "original_name": "Non-HDL Cholesterol",
                    "value": round(tc["value"] - hdl["value"], 2),
                    "unit": tc["unit"],
                    "ref_low": None,
                    "ref_high": None,
                    "source": "calculated",
                    "method": (
                        f"total_cholesterol (BM027) {tc['value']} − "
                        f"hdl (BM029) {hdl['value']} [{tc['unit']}]"
                    ),
                }
            )

    # Transferrin saturation (BM037).
    if _first(results, "BM037") is None:
        iron, tibc = _first(results, "BM035"), _first(results, "BM036")
        if (
            iron is not None
            and tibc is not None
            and tibc["value"] != 0
            and _compatible(iron, tibc)
        ):
            results.append(
                {
                    "biomarker_id": "BM037",
                    "standard_name": "Transferrin Saturation",
                    "original_name": "Transferrin Saturation",
                    "value": round(iron["value"] / tibc["value"] * 100, 1),
                    "unit": "%",
                    "ref_low": None,
                    "ref_high": None,
                    "source": "calculated",
                    "method": (
                        f"serum_iron (BM035) {iron['value']} / "
                        f"tibc (BM036) {tibc['value']} × 100 [{iron['unit']}]"
                    ),
                }
            )

    return results
