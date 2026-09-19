"""Shared LLM client. Best-effort, fails gracefully to None.

Priority: Google Gemini (GEMINI_API_KEY env var, free tier) -> local Ollama
(http://localhost:11434, free/offline) -> None. Nothing here is required for
the app to work; callers must handle None.
"""
import os

import requests

GEMINI_MODEL = "gemini-2.0-flash"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1"


def _gemini_complete(prompt: str, system: str) -> str | None:
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
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": prompt}]}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return None


def _ollama_complete(prompt: str, system: str) -> str | None:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "system": system,
                "prompt": prompt,
                "stream": False,
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json().get("response") or None
    except Exception:
        return None


def complete(prompt: str, system: str = "") -> tuple[str | None, str | None]:
    """Return (text, model_name), or (None, None) when no backend is up."""
    text = _gemini_complete(prompt, system)
    if text:
        return text, GEMINI_MODEL
    text = _ollama_complete(prompt, system)
    if text:
        return text, OLLAMA_MODEL
    return None, None
