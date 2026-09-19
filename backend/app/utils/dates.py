"""Report-date extraction from lab-report text.

Tries common date formats, preferring dates attached to labels like
"Report Date:" or "Collected:". Falls back to the upload date when nothing
is found. Assumes US-style MM/DD/YYYY for ambiguous numeric dates.
"""
import re
from datetime import date

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Date-shaped fragments we know how to parse.
_DATE_FRAG = (
    r"(?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}"      # Jan 15, 2026
    r"|\d{1,2}-[A-Za-z]{3}-\d{2,4}"                # 15-Jan-2026
    r"|\d{4}-\d{1,2}-\d{1,2}"                     # 2026-01-15
    r"|\d{1,2}/\d{1,2}/\d{2,4})"                  # 01/15/2026
)

# Labeled dates ("Report Date: ...", "Collected: ...") get first priority.
_LABELED = re.compile(
    r"(?:report date|date of report|collected(?: on)?|collection date|"
    r"date collected|specimen collected|drawn(?: on)?)\s*:?\s*(" + _DATE_FRAG + r")",
    re.IGNORECASE,
)
_GENERIC = re.compile(_DATE_FRAG)


def _parse_fragment(frag: str) -> date | None:
    frag = frag.strip()
    try:
        # "Jan 15, 2026" / "January 15 2026"
        m = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{2,4})", frag)
        if m:
            month = _MONTHS[m.group(1).lower()]
            year = int(m.group(3))
            return date(year + 2000 if year < 100 else year, month, int(m.group(2)))
        # "15-Jan-2026"
        m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})", frag)
        if m:
            month = _MONTHS[m.group(2).lower()]
            year = int(m.group(3))
            return date(year + 2000 if year < 100 else year, month, int(m.group(1)))
        # "2026-01-15"
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", frag)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        # "01/15/2026" (MM/DD/YYYY)
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", frag)
        if m:
            year = int(m.group(3))
            return date(year + 2000 if year < 100 else year, int(m.group(1)), int(m.group(2)))
    except (ValueError, KeyError):
        return None
    return None


def parse_report_date(text: str, fallback: date | None = None) -> date:
    """Extract the report date from *text*, or *fallback* (default: today)."""
    if fallback is None:
        fallback = date.today()
    if not text:
        return fallback
    labeled = _LABELED.search(text)
    if labeled:
        parsed = _parse_fragment(labeled.group(1))
        if parsed:
            return parsed
    generic = _GENERIC.search(text)
    if generic:
        parsed = _parse_fragment(generic.group(0))
        if parsed:
            return parsed
    return fallback
