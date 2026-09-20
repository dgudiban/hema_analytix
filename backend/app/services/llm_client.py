"""Shared LLM client. Best-effort, fails gracefully to None.

Priority: Groq (GROQ_API_KEY env var, free tier) -> Google Gemini
(GEMINI_API_KEY env var, free tier) -> local Ollama
(http://localhost:11434, free/offline) -> None. Nothing here is required for
the app to work; callers must handle None.
"""
import os

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_MODEL = "gemini-3.6-flash"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1"


def _groq_model() -> str:
    # Overridable via env; default verified against Groq's free tier.
    return os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")


def _groq_complete(prompt: str, system: str, max_tokens: int = 1024) -> str | None:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": _groq_model(),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
            timeout=90,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return content or None
    except Exception:
        return None


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


def complete(
    prompt: str, system: str = "", max_tokens: int = 1024
) -> tuple[str | None, str | None]:
    """Return (text, model_name), or (None, None) when no backend is up."""
    text = _groq_complete(prompt, system, max_tokens=max_tokens)
    if text:
        return text, _groq_model()
    text = _gemini_complete(prompt, system)
    if text:
        return text, GEMINI_MODEL
    text = _ollama_complete(prompt, system)
    if text:
        return text, OLLAMA_MODEL
    return None, None
