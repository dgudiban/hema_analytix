"""Unit string helpers."""


def normalize_unit(unit: str | None) -> str:
    """Light unit normalization for compatibility checks.

    Lowercases, maps µ -> u, and drops spaces so "K/µL", "k/ul" and "K / µL"
    compare equal. This is equality-only: no unit *conversion* is performed.
    """
    return (unit or "").lower().replace("µ", "u").replace(" ", "")
