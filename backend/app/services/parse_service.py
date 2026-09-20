"""Regex-based biomarker finder with reference-range capture.

For each biomarker spec entry we try its standard name plus its aliases
(longest first) against the extracted report text, capturing the numeric value
(thousands commas handled), an optional trailing unit, and the reference range
printed on the report (e.g. "(12.0-15.5)", "Ref 4,000-11,000", "> 60", "< 200").

Matched character spans are marked as consumed so shorter aliases (e.g.
"Cholesterol") don't double-match inside longer ones ("Total Cholesterol").
Hyphen-aware word boundaries stop subtype merges: "hs-CRP" never matches the
"CRP" alias and "RDW-SD" never matches "RDW". Unparseable numbers are skipped
gracefully.

There is deliberately NO fallback to any hard-coded reference ranges: when the
report prints no range, ref_low/ref_high stay None and the status becomes
"unknown" downstream.
"""
import re

# A number such as 6,500 | 210,000 | 13.2 | 4.5
_NUMBER = r"(?P<value>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
# Same, without a capture-group name (for embedding inside range patterns).
_RANGE_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"

# Lab-printed abnormality flags, e.g. "12.5 Low 13.0 - 17.0 g/dL".
_FLAG_WORDS = r"[Ll]ow|[Hh]igh|[Bb]orderline|[Nn]ormal|[Aa]bnormal"
_FLAG_RE = re.compile(rf"\b({_FLAG_WORDS})\b")

# Optional "(ABBR)" between a biomarker name and its value,
# e.g. "Hemoglobin (Hb) 12.5" or "Packed Cell Volume (PCV) 57.5".
_PAREN_ABBR = r"(?:\s*\([^()\n]{1,16}\))?"

# Curated unit vocabulary — deliberately restrictive so a following word
# (e.g. the next line's biomarker name) is never swallowed as a "unit".
_UNIT_TOKEN = (
    r"K/µL|K/uL|million/µL|mill/cumm|mL/min/1\.73\s?m²|mL/min/1\.73\s?m2|"
    r"µIU/mL|uIU/mL|µg/dL|ug/dL|mmol/L|mEq/L|mg/dL|mg/L|g/dL|"
    r"ng/dL|ng/mL|pg/mL|mIU/L|mm/hr|U/L|fL|pg|%|/µL|/uL|/cumm|cumm"
)

# Optional separator between a biomarker name and its value: ":  ", " - ", " = ", "  "
_SEP = r"\s*[:=\-–]?\s*"

# Reference-range shapes found after the value/unit on the same line.
# Bare "lo - hi" covers reports that print the range with no parens and no
# "Ref" label, e.g. "12.5 Low 13.0 - 17.0 g/dL" or "9000 4000-11000 cumm".
_PAREN_RANGE = re.compile(
    r"\(\s*(?P<lo>" + _RANGE_NUM + r")\s*(?:-|–|to)\s*(?P<hi>" + _RANGE_NUM + r")\s*\)"
)
_REF_RANGE = re.compile(
    r"\b[Rr]ef(?:erence)?(?:\s+[Rr]ange)?\s*:?\s*"
    r"(?P<lo>" + _RANGE_NUM + r")\s*(?:-|–|to)\s*(?P<hi>" + _RANGE_NUM + r")"
)
_ONE_SIDED = re.compile(
    r"\(?\s*(?P<comp>[<>≤≥]=?)\s*(?P<num>" + _RANGE_NUM + r")\s*\)?"
)
_BARE_RANGE = re.compile(
    r"(?:\b(?:" + _FLAG_WORDS + r")\b\s+)?"
    r"(?P<lo>" + _RANGE_NUM + r")\s*(?:-|–|to)\s*(?P<hi>" + _RANGE_NUM + r")"
    r"(?=\s*(?:" + _UNIT_TOKEN + r")?(?!\w))"
)


# Subtype guard: preceding tokens that prove the match is a DIFFERENT analyte
# than the biomarker entry, so it must not merge. (Hyphen-aware boundaries in
# _alias_pattern already block forms like "hs-CRP" -> "CRP" or "RDW-SD" -> "RDW".)
_SUBTYPE_GUARDS = {
    "BM009": {"sd"},                                        # "RDW SD"
    "BM019": {"ionized"},                                   # ionized calcium
    "BM038": {"1,25", "1,25-dihydroxy", "1,25-(oh)2"},      # other D metabolites
    "BM040": {"rbc", "red cell", "erythrocyte"},            # RBC folate
    "BM041": {"hs", "high-sensitivity", "high sensitivity"},  # hs-CRP
}


def _is_guarded_subtype(biomarker_id: str, text: str, start: int) -> bool:
    """True when the token(s) before *start* mark a distinct subtype."""
    guards = _SUBTYPE_GUARDS.get(biomarker_id)
    if not guards:
        return False
    tail = text[max(0, start - 32) : start].rstrip().lower()
    return any(tail == g or tail.endswith(" " + g) for g in guards)


def _alias_pattern(alias: str) -> re.Pattern:
    # Hyphen-aware boundaries: "hs-CRP" must not match alias "CRP",
    # "RDW-SD" must not match alias "RDW". An optional "(ABBR)" may sit
    # between the name and the value: "Hemoglobin (Hb) 12.5".
    return re.compile(
        rf"(?<![\w-])(?P<alias>{re.escape(alias)})(?![\w-]){_PAREN_ABBR}{_SEP}{_NUMBER}"
        rf"\s?(?P<unit>{_UNIT_TOKEN})?(?!\w)",
        re.IGNORECASE,
    )


def _open_value_pattern(alias: str) -> re.Pattern:
    """Alias followed directly by a comparator, e.g. "eGFR > 60".

    Some reports print one-sided results this way: the number doubles as the
    value and as the open-ended bound.
    """
    return re.compile(
        rf"(?<![\w-])(?P<alias>{re.escape(alias)})(?![\w-]){_SEP}"
        rf"(?P<comp>[<>≤≥])\s*{_NUMBER}\s?(?P<unit>{_UNIT_TOKEN})?(?!\w)",
        re.IGNORECASE,
    )


def _to_float(raw: str) -> float | None:
    """Strip thousands separators and parse; None when not a number."""
    try:
        return float(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _parse_reference_range(suffix: str) -> tuple[float | None, float | None, int | None]:
    """Find a reference range in *suffix* (text after value/unit, same line).

    Returns (ref_low, ref_high, range_end); either bound may be None for
    open-ended ranges, and range_end is the index just past the matched range
    (None when no range is printed) so a trailing unit can be recovered.
    """
    best: tuple[int, str, re.Match] | None = None
    for kind, pattern in (
        ("two", _PAREN_RANGE),
        ("two", _REF_RANGE),
        ("one", _ONE_SIDED),
        ("two", _BARE_RANGE),
    ):
        match = pattern.search(suffix)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), kind, match)
    if best is None:
        return None, None, None
    _, kind, match = best
    if kind == "two":
        return (
            _to_float(match.group("lo")),
            _to_float(match.group("hi")),
            match.end(),
        )
    comp = match.group("comp")
    num = _to_float(match.group("num"))
    if comp.startswith((">", "≥")):
        return num, None, match.end()
    return None, num, match.end()


def _unit_after_range(suffix: str, range_end: int | None) -> str | None:
    """Unit printed after the reference range, e.g. "5.2 4.5 - 5.5 mill/cumm".

    Columnar layouts can separate the range and unit by wide whitespace.
    """
    if range_end is None:
        return None
    match = re.match(
        r"\s*(?P<unit>" + _UNIT_TOKEN + r")(?!\w)", suffix[range_end : range_end + 80]
    )
    return match.group("unit").strip() if match else None


def _parse_flag(suffix: str) -> str | None:
    """The lab's own printed flag (Low/High/Borderline/...) after the value.

    This is transcription of report text, never a computed judgment.
    """
    match = _FLAG_RE.search(suffix[:80])
    if not match:
        return None
    return match.group(1)[0].upper() + match.group(1)[1:].lower()


def extract_interpretation(text: str) -> str | None:
    """The lab's own "Interpretation:" line, quoted verbatim when present."""
    match = re.search(r"(?im)^\s*interpretation\s*:\s*(.+?)\s*$", text)
    if not match:
        return None
    return match.group(1).strip() or None


def _line_suffix(text: str, end: int) -> str:
    """Text from *end* to the end of the line (capped), where ranges live.

    The cap is generous (200 chars) because columnar lab layouts can put the
    reference range and unit far to the right of the value.
    """
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    return text[end : min(line_end, end + 200)]


def _overlaps(consumed: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(s < end and start < e for s, e in consumed)


def parse_text(text: str, spec: list[dict]) -> list[dict]:
    """Find biomarker values and their report-printed reference ranges.

    Each spec entry contributes its ``standard_name`` plus ``common_aliases``
    as match candidates — strictly via these lists, so subtypes that are not
    aliases (RDW-SD, hs-CRP, ionized calcium, RBC folate, ...) never merge
    into the wrong entry.

    Returns dicts {biomarker_id, standard_name, original_name, value, unit,
    ref_low, ref_high, flag} in spec order. ``original_name`` is the test name
    as written in the report (traceability); ``flag`` is the lab's own printed
    flag word (Low/High/Borderline/...) when present, else None. When the text
    has no unit after the number, the spec's ``typical_units`` is used.
    """
    consumed: list[tuple[int, int]] = []
    found: dict[str, dict] = {}

    def _names(bm: dict) -> list[str]:
        return [n for n in [bm["standard_name"], *bm["common_aliases"]] if n]

    # Longest alias first, across all biomarkers, to avoid partial matches.
    jobs = [(len(alias), bm, alias) for bm in spec for alias in _names(bm)]
    jobs.sort(key=lambda job: -job[0])

    for _, bm, alias in jobs:
        bid = bm["biomarker_id"]
        if bid in found:
            continue  # already matched via a longer alias
        for match in _alias_pattern(alias).finditer(text):
            start, end = match.start(), match.end()
            if _overlaps(consumed, start, end):
                continue  # overlaps an earlier (longer-alias) match
            if _is_guarded_subtype(bid, text, start):
                continue  # distinct subtype (e.g. ionized calcium) — don't merge
            value = _to_float(match.group("value"))
            if value is None:
                continue
            raw_unit = (match.group("unit") or "").strip()
            suffix = _line_suffix(text, end)
            ref_low, ref_high, range_end = _parse_reference_range(suffix)
            unit = raw_unit or _unit_after_range(suffix, range_end) or bm["typical_units"]
            consumed.append((start, end))
            found[bid] = {
                "biomarker_id": bid,
                "standard_name": bm["standard_name"],
                "original_name": match.group("alias"),
                "value": value,
                "unit": unit,
                "ref_low": ref_low,
                "ref_high": ref_high,
                "flag": _parse_flag(suffix),
            }
            break  # first good match per biomarker

    # Fallback pass: open-ended "alias > 60" style lines for unmatched markers.
    for bm in spec:
        bid = bm["biomarker_id"]
        if bid in found:
            continue
        for alias in sorted(_names(bm), key=len, reverse=True):
            match = _open_value_pattern(alias).search(text)
            if match is None or _overlaps(consumed, match.start(), match.end()):
                continue
            if _is_guarded_subtype(bid, text, match.start()):
                continue  # distinct subtype — don't merge
            value = _to_float(match.group("value"))
            if value is None:
                continue
            raw_unit = (match.group("unit") or "").strip()
            if match.group("comp") in (">", "≥"):
                ref_low, ref_high = value, None
            else:
                ref_low, ref_high = None, value
            consumed.append((match.start(), match.end()))
            found[bid] = {
                "biomarker_id": bid,
                "standard_name": bm["standard_name"],
                "original_name": match.group("alias"),
                "value": value,
                "unit": raw_unit or bm["typical_units"],
                "ref_low": ref_low,
                "ref_high": ref_high,
                "flag": _parse_flag(_line_suffix(text, match.end())),
            }
            break

    # Preserve spec order in the output.
    return [found[bm["biomarker_id"]] for bm in spec if bm["biomarker_id"] in found]
