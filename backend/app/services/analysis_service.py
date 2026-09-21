"""Rule-based abnormality detection.

Each value is compared ONLY against the reference range printed on its own
lab report. When the report gives no range, the lab's own printed flag
(Low/High/Normal) is transcribed when present; otherwise the status is
"unknown". There is deliberately no fallback to hard-coded ranges. This is
deterministic code, never an LLM decision.

One narrow exception: for biomarkers whose reports print multiple category
bands (e.g. Vitamin D: Deficiency <10 / Insufficiency 10-30 / Sufficiency
30-100), the AI must transcribe the healthy ("sufficiency/optimal") band and
sometimes picks a low/high category band instead. A wrongly-picked band is
detected and replaced with the canonical healthy band — but only when the lab
printed no flag, the transcribed band cannot overlap the healthy band, and the
unit matches. A printed abnormal flag still wins, and a correctly transcribed
band is never touched.
"""

# Lab-printed flag -> status. An abnormal flag is the lab's own verdict from the
# correct reference band, so it wins over the transcribed range: the AI can
# pick the wrong band from multi-band references (e.g. "Near optimal: 100-129"
# instead of "Optimal: <100"), but the flag is the lab's authoritative call.
_FLAG_STATUS = {"Low": "LOW", "High": "HIGH", "Normal": "NORMAL"}

# biomarker_id -> canonical healthy band, used ONLY to detect a mis-picked
# multi-band transcription (see _canonical_band). Units gate the rule because
# healthy cutoffs differ across units (e.g. Vitamin D in nmol/L).
CANONICAL_BANDS = {
    # 25(OH) Vitamin D: sufficiency band 30-100 ng/mL (Endocrine Society).
    "BM038": {"ref_low": 30.0, "ref_high": 100.0, "units": {"ng/ml"}},
}


def _canonical_band(item: dict) -> tuple[float | None, float | None] | None:
    """Return the canonical healthy band if the transcribed band was mis-picked.

    Returns None (keep the transcribed band) when: no canonical band is known
    for this biomarker, the lab printed a flag, the unit doesn't match, or the
    transcribed band overlaps the canonical band (then it is plausibly the
    lab's own healthy band, possibly with lab-specific bounds).
    """
    spec = CANONICAL_BANDS.get(item.get("biomarker_id") or "")
    if not spec or item.get("flag"):
        return None
    unit = (item.get("unit") or "").strip().lower()
    if unit not in spec["units"]:
        return None
    lo, hi = item.get("ref_low"), item.get("ref_high")
    c_lo, c_hi = spec["ref_low"], spec["ref_high"]
    # Mis-picked band: entirely at/below the canonical low bound, or entirely
    # at/above the canonical high bound (e.g. Deficiency None-10 vs canonical
    # 30-100). The canonical band mirrors the report's own printed healthy
    # band, so the substituted bounds still come from the report itself.
    if hi is not None and c_lo is not None and hi <= c_lo:
        return (c_lo, c_hi)
    if lo is not None and c_hi is not None and lo >= c_hi:
        return (c_lo, c_hi)
    return None


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
    out = []
    for item in results:
        band = _canonical_band(item)
        if band is not None:
            item = {**item, "ref_low": band[0], "ref_high": band[1]}
        out.append(
            {
                **item,
                "status": flag_status(
                    item["value"], item.get("ref_low"), item.get("ref_high"),
                    item.get("flag"),
                ),
            }
        )
    return out


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
        return "Analyzed 0 biomarker(s): 0 normal. Educational summary only — not a diagnosis."

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
