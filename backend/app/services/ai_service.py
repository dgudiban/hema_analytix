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
    "You are LabIQ's friendly health explainer. You explain lab results in "
    "plain, warm, everyday language that a person with no medical background "
    "can easily understand. This is educational information, not medical "
    "advice. Never diagnose a condition, prescribe anything, or recommend "
    "treatments. Always end by reminding the reader to discuss their results "
    "with their doctor."
)


def _build_prompt(results: list[dict], summary: str) -> str:
    abnormal = [r for r in results if r["status"] in ("LOW", "HIGH")]
    normal = [r for r in results if r["status"] == "NORMAL"]
    lines = [
        f"- {r['standard_name']}: {r['value']} {r['unit']} "
        f"(reference {_ref_str(r)}) [{r['status']}]"
        + (f" — lab flagged it {r['flag']}" if r.get("flag") else "")
        for r in results
    ]
    return (
        f"Summary: {summary}\n\n"
        "Results:\n" + "\n".join(lines) + "\n\n"
        "Write a friendly explanation of this lab report for the person it "
        "belongs to. Do NOT use a table — write in short paragraphs and "
        "bullet points a non-medical person can understand.\n\n"
        "Structure it like this:\n"
        "1. One short opening paragraph: how many tests were checked, how "
        "many are in range, and the overall picture in one calm sentence.\n"
        "2. 'What needs a closer look' — for each result marked LOW or HIGH, "
        "one short bullet: what the test measures in one simple clause, "
        "your value, the reference range printed on your report, and in "
        "general terms what can make it go high or low. Never say the "
        "person has a condition. If a test has no printed reference range, "
        "say so plainly ('your report doesn't print a range for this one') "
        "and go by the lab's own flag.\n"
        "3. 'What's looking good' — one sentence naming the tests that are "
        "in range (if every test needs a closer look, say so in one line).\n"
        "4. 'What to do next' — one short paragraph: talk through the "
        "abnormal results with your doctor, and one or two useful questions "
        "to ask them. Keep it reassuring, never alarming.\n\n"
        "Rules: short sentences, no unexplained medical jargon, no table, "
        "no markdown table. End with exactly this line on its own: "
        "'Educational summary only — not a diagnosis.'"
    )


CLOSING_LINE = "Educational summary only — not a diagnosis."


def ensure_closing_line(text: str | None) -> str | None:
    """Append the required closing line unless the text already ends with it."""
    if text and not text.strip().endswith(CLOSING_LINE):
        return text.rstrip() + "\n\n" + CLOSING_LINE
    return text


def explain_report(results: list[dict], summary: str) -> str | None:
    """Return an AI explanation, or None when no AI backend is available."""
    if not results:
        return None
    text, _ = llm_client.complete(_build_prompt(results, summary), SYSTEM)
    return text
