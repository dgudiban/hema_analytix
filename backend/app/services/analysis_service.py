"""Rule-based abnormality detection.

Each value is compared ONLY against the reference range printed on its own
lab report. When the report gives no range, the lab's own printed flag
(Low/High/Normal) is transcribed when present; otherwise the status is
"unknown". There is deliberately no fallback to hard-coded ranges. This is
deterministic code, never an LLM decision.
"""

# Lab-printed flag -> status. An abnormal flag is the lab's own verdict from the
# correct reference band, so it wins over the transcribed range: the AI can
# pick the wrong band from multi-band references (e.g. "Near optimal: 100-129"
# instead of "Optimal: <100"), but the flag is the lab's authoritative call.
_FLAG_STATUS = {"Low": "LOW", "High": "HIGH", "Normal": "NORMAL"}


def flag_status(
    value: float,
    ref_low: float | None,
    ref_high: float | None,
    flag: str | None = None,
) -> str:
    """LOW / HIGH / NORMAL / unknown from the report's own data.

    An abnormal printed flag (High/Low) always decides the status — it is the
    lab's verdict. Otherwise the value is compared against the printed range:
    one-sided ranges use the single bound (value > ref_high -> HIGH with only
    ref_high; value < ref_low -> LOW with only ref_low). With no range and no
    abnormal flag, a printed Normal flag transcribes to NORMAL; anything else
    is unknown.
    """
    if flag == "High":
        return "HIGH"
    if flag == "Low":
        return "LOW"
    if ref_low is None and ref_high is None:
        return _FLAG_STATUS.get(flag or "", "unknown")
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
                item["value"], item.get("ref_low"), item.get("ref_high"),
                item.get("flag"),
            ),
        }
        for item in results
    ]


def _fmt_num(value: float) -> str:
    return f"{value:g}"


def _fmt_range(item: dict) -> str:
    lo, hi = item.get("ref_low"), item.get("ref_high")
    if lo is None and hi is None:
        return ""
    if lo is None:
        return f"< {_fmt_num(hi)}"
    if hi is None:
        return f"> {_fmt_num(lo)}"
    return f"{_fmt_num(lo)}–{_fmt_num(hi)}"


def summarize(results: list[dict], interpretation: str | None = None) -> str:
    """Short findings summary of the analysis, shown right after upload.

    Lists every out-of-range result with its value, the report's reference
    range, and the lab's printed flag; quotes the lab's own interpretation
    line when the report has one. Educational only — never a diagnosis.
    """
    if not results:
        return "Analyzed 0 biomarker(s): 0 normal."

    abnormal = [r for r in results if r["status"] in ("LOW", "HIGH")]
    unknowns = [r for r in results if r["status"] == "unknown"]
    normals = len(results) - len(abnormal) - len(unknowns)

    parts = [f"Analyzed {len(results)} biomarker(s): {normals} normal"]
    if abnormal:
        items = []
        for r in abnormal:
            seg = (
                f"{r['standard_name']} {r['status']} at "
                f"{_fmt_num(r['value'])} {r['unit']}"
            )
            bits = []
            rng = _fmt_range(r)
            if rng:
                bits.append(f"ref {rng}")
            if r.get("flag"):
                bits.append(f"lab flag: {r['flag']}")
            if bits:
                seg += " (" + ", ".join(bits) + ")"
            items.append(seg)
        parts.append(f"{len(abnormal)} outside reference range — " + "; ".join(items))
    if unknowns:
        items = []
        for r in unknowns:
            seg = r["standard_name"]
            if r.get("flag"):
                seg += f" (lab flag: {r['flag']}; no range printed)"
            items.append(seg)
        parts.append(
            f"{len(unknowns)} without a reference range on the report "
            f"({', '.join(items)})"
        )
    text = "; ".join(parts) + "."
    if interpretation:
        interp = interpretation.strip()
        if interp and not interp.endswith((".", "!", "?")):
            interp += "."
        text += f" Lab interpretation: {interp}"
    text += " Educational summary only — not a diagnosis."
    return text
