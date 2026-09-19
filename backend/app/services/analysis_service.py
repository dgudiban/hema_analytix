"""Rule-based abnormality detection.

Each value is compared ONLY against the reference range printed on its own
lab report. When the report gives no range, the status is "unknown" — there
is deliberately no fallback to hard-coded ranges. This is deterministic code,
never an LLM decision.
"""


def flag_status(
    value: float, ref_low: float | None, ref_high: float | None
) -> str:
    """LOW / HIGH / NORMAL / unknown from the report's own reference range.

    One-sided ranges: with only ref_high, value > ref_high -> HIGH else
    NORMAL; with only ref_low, value < ref_low -> LOW else NORMAL.
    """
    if ref_low is None and ref_high is None:
        return "unknown"
    if ref_low is not None and value < ref_low:
        return "LOW"
    if ref_high is not None and value > ref_high:
        return "HIGH"
    return "NORMAL"


def analyze(results: list[dict]) -> list[dict]:
    """Attach a status to each normalized result."""
    return [
        {
            **item,
            "status": flag_status(
                item["value"], item.get("ref_low"), item.get("ref_high")
            ),
        }
        for item in results
    ]


def summarize(results: list[dict]) -> str:
    """One-paragraph rule-based summary of the analysis."""
    lows = [r for r in results if r["status"] == "LOW"]
    highs = [r for r in results if r["status"] == "HIGH"]
    unknowns = [r for r in results if r["status"] == "unknown"]
    normals = len(results) - len(lows) - len(highs) - len(unknowns)

    parts = [f"Analyzed {len(results)} biomarker(s): {normals} normal"]
    if lows:
        parts.append(f"{len(lows)} low ({', '.join(r['standard_name'] for r in lows)})")
    if highs:
        parts.append(f"{len(highs)} high ({', '.join(r['standard_name'] for r in highs)})")
    if unknowns:
        parts.append(
            f"{len(unknowns)} without a reference range on the report "
            f"({', '.join(r['standard_name'] for r in unknowns)})"
        )
    if not lows and not highs and not unknowns and results:
        parts.append("all values within their reference ranges")
    return "; ".join(parts) + "."
