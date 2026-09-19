"""Optional AI explanations, built on the shared LLM client.

Every AI path is best-effort and fails gracefully: when no LLM backend is
available, explain_report returns None and the API falls back to the
rule-based summary. Nothing here is required for the app to work.
"""
from app.services import llm_client


def _ref_str(r: dict) -> str:
    lo, hi = r.get("ref_low"), r.get("ref_high")
    if lo is None and hi is None:
        return "no reference range on report"
    if lo is None:
        return f"< {hi}"
    if hi is None:
        return f"> {lo}"
    return f"{lo}–{hi}"


SYSTEM = (
    "You are a helpful assistant explaining blood test results in plain, "
    "non-alarming language. This is educational information, not medical "
    "advice. Never diagnose, prescribe, or recommend treatments. Remind the "
    "reader to discuss results with their doctor."
)


def _build_prompt(results: list[dict], summary: str) -> str:
    lines = [
        f"- {r['standard_name']} ({r['original_name']}): {r['value']} {r['unit']} "
        f"(reference {_ref_str(r)}) [{r['status']}]"
        for r in results
    ]
    return (
        f"Summary: {summary}\n\n"
        "Results:\n" + "\n".join(lines) + "\n\n"
        "Briefly explain the abnormal values and what they may relate to."
    )


def explain_report(results: list[dict], summary: str) -> str | None:
    """Return an AI explanation, or None when no AI backend is available."""
    if not results:
        return None
    text, _ = llm_client.complete(_build_prompt(results, summary), SYSTEM)
    return text
