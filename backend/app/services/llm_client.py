"""Shared LLM client. Best-effort, fails gracefully to None.

Priority: Groq (GROQ_API_KEY env var, free tier) -> Google Gemini
(GEMINI_API_KEY env var, free tier) -> local Ollama
(http://localhost:11434, free/offline) -> None. Nothing here is required for
the app to work; callers must handle None.

Diagnostic: after each complete() call, module-level last_error is None on
success or a short tag describing every backend failure, e.g.
"groq:http_429" or "groq:timeout,ollama:request_error" — so callers can
report *why* a chunk failed instead of just seeing (None, None).
"""
import os
import re

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_MODEL = "gemini-3.6-flash"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1"

last_error: str | None = None


def _http_error_tag(exc: requests.HTTPError) -> str:
    """Build an error tag like http_429:<rate-limit detail from the body>.

    Groq's 429 body names the exact limit that tripped, e.g.
    "Rate limit reached ... on tokens per minute (TPM): Limit 8000,
    Used 7900, Requested 3100" — far more useful than the bare status.
    """
    code = exc.response.status_code if exc.response is not None else "?"
    tag = f"http_{code}"
    try:
        body = exc.response.json() if exc.response is not None else {}
        err = body.get("error") if isinstance(body, dict) else None
        msg = err.get("message", "") if isinstance(err, dict) else ""
        msg = re.sub(r"\s+", " ", str(msg)).strip()
        msg = re.sub(r"org[-_][A-Za-z0-9]+", "org-…", msg)  # keep org ids out
        if msg:
            tag += ":" + msg[:180]
    except Exception:
        pass
    return tag


def _groq_models() -> list[str]:
    """Groq models to try in order. Quotas are per model, so a second model
    is a fresh quota pool when the first is exhausted."""
    raw = os.environ.get("GROQ_MODELS", "")
    models = [m.strip() for m in raw.split(",") if m.strip()]
    # gpt-oss-20b: same family, production tier, own 200k/day quota pool.
    # (llama-3.3-70b-versatile moved to Enterprise-only; 404s on free tier.)
    return models or ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def _groq_one(
    prompt: str, system: str, model: str, max_tokens: int = 1024
) -> tuple[str | None, str | None]:
    """Single-model Groq call. Return (text, error_tag); error_tag None on success."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None, "no_key"
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    if "gpt-oss" in model:
        # gpt-oss is a reasoning model; hidden reasoning tokens count against
        # the free TPM quota, so keep reasoning minimal for transcription.
        body["reasoning_effort"] = "low"
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=90,
        )
        resp.raise_for_status()
    except requests.Timeout:
        return None, "timeout"
    except requests.HTTPError as exc:
        return None, _http_error_tag(exc)
    except requests.RequestException:
        return None, "request_error"
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None, "bad_response"
    return (content or None), (None if content else "empty")


def _gemini_complete(prompt: str, system: str) -> tuple[str | None, str | None]:
    """Return (text, error_tag); error_tag is None on success."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, "no_key"
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
    except requests.Timeout:
        return None, "timeout"
    except requests.HTTPError as exc:
        return None, _http_error_tag(exc)
    except requests.RequestException:
        return None, "request_error"
    try:
        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return None, "bad_response"
    return (content or None), (None if content else "empty")


def _ollama_complete(prompt: str, system: str) -> tuple[str | None, str | None]:
    """Return (text, error_tag); error_tag is None on success."""
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
    except requests.Timeout:
        return None, "timeout"
    except requests.HTTPError as exc:
        return None, _http_error_tag(exc)
    except requests.RequestException:
        return None, "request_error"
    try:
        content = resp.json().get("response")
    except Exception:
        return None, "bad_response"
    return (content or None), (None if content else "empty")


def complete(
    prompt: str,
    system: str = "",
    max_tokens: int = 1024,
    model_order: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """Return (text, model_name), or (None, None) when no backend is up.

    Groq models are tried in order (quotas are per model, so a second model
    is a fresh quota pool when the first is exhausted). Pass model_order to
    prefer a specific model for a workload, e.g. a high-TPM model for
    token-heavy extraction.

    After the call, module-level last_error is None on success, or a short
    tag naming every backend failure, e.g. "groq:http_429",
    "groq:timeout,ollama:request_error", or "no_backend" when no backend is
    configured at all.
    """
    global last_error
    last_error = None
    failures: list[str] = []

    for model in model_order or _groq_models():
        text, err = _groq_one(prompt, system, model, max_tokens=max_tokens)
        if text:
            return text, model
        if err != "no_key":
            failures.append(f"groq:{err}")
        else:
            break  # no key configured; don't try more Groq models

    text, err = _gemini_complete(prompt, system)
    if text:
        return text, GEMINI_MODEL
    if err != "no_key":
        failures.append(f"gemini:{err}")

    text, err = _ollama_complete(prompt, system)
    if text:
        return text, OLLAMA_MODEL
    if err:
        failures.append(f"ollama:{err}")

    last_error = ",".join(failures) if failures else "no_backend"
    return None, None
