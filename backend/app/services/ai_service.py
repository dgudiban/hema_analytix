"""Optional AI explanations. Every AI path is best-effort and fails gracefully.

Priority: Google Gemini (GEMINI_API_KEY env var, free tier) -> local Ollama
(http://localhost:11434, free/offline) -> None (API falls back to the
rule-based summary). Nothing here is required for the app to work.
"""
import os

import requests

GEMINI_MODEL = "gemini-2.0-flash"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1"


def _ref_str(r: dict) -> str:
    lo, hi = r.get("ref_low"), r.get("ref_high")
    if lo is None and hi is None:
        return "no reference range on report"
    if lo is None:
        return f"< {hi}"
    if hi is None:
        return f"> {lo}"
    return f"{lo}–{hi}"


def _build_prompt(results: list[dict], summary: str) -> str:
    lines = [
        f"- {r['standard_name']} ({r['original_name']}): {r['value']} {r['unit']} "
        f"(reference {_ref_str(r)}) [{r['status']}]"
        for r in results
    ]
    return (
        "You are a helpful assistant explaining blood test results in plain, "
        "non-alarming language. This is not medical advice; remind the reader "
        "to discuss results with their doctor.\n\n"
        f"Summary: {summary}\n\n"
        "Results:\n" + "\n".join(lines) + "\n\n"
        "Briefly explain the abnormal values and what they may relate to."
    )


def _gemini_explain(results: list[dict], summary: str) -> str | None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    try:
        resp = requests.post(
            url,
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": _build_prompt(results, summary)}]}]},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return None  # network/quota/parse issue — fall through to the next option


def _ollama_explain(results: list[dict], summary: str) -> str | None:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": _build_prompt(results, summary),
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response") or None
    except Exception:
        return None  # Ollama not running — caller falls back to rule-based text


def explain_report(results: list[dict], summary: str) -> str | None:
    """Return an AI explanation, or None when no AI backend is available."""
    if not results:
        return None
    explanation = _gemini_explain(results, summary)
    if explanation:
        return explanation
    return _ollama_explain(results, summary)
