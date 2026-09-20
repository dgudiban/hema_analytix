"""Unit string helpers."""

# Canonical equivalences (equality-only; no value conversion is performed).
# 1 cubic millimeter == 1 microliter, so "cumm" == "/uL".
_EQUIVALENT_UNITS = {
    "cumm": "/ul",
    "/cumm": "/ul",
    "cu.mm": "/ul",
    "mill/cumm": "million/ul",
    "mill/cu.mm": "million/ul",
    "mill/ul": "million/ul",
}


def normalize_unit(unit: str | None) -> str:
    """Light unit normalization for compatibility checks.

    Lowercases, maps µ -> u, and drops spaces so "K/µL", "k/ul" and "K / µL"
    compare equal, then maps known-equivalent spellings ("cumm" -> "/ul").
    This is equality-only: no unit *conversion* is performed.
    """
    canonical = (unit or "").lower().replace("µ", "u").replace(" ", "")
    return _EQUIVALENT_UNITS.get(canonical, canonical)
