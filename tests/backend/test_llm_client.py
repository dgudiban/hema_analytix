"""Tests for llm_client failure diagnostics (error tags + last_error)."""
from unittest.mock import Mock, patch

import pytest
import requests

from app.services import llm_client


def _http_error(status):
    err = requests.HTTPError(f"{status} error")
    err.response = Mock(status_code=status)
    return err


def test_groq_http_429_is_tagged(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with patch.object(
        llm_client.requests, "post", side_effect=_http_error(429)
    ):
        text, err = llm_client._groq_one("hi", "sys", "openai/gpt-oss-120b")
    assert (text, err) == (None, "http_429")


def test_groq_timeout_is_tagged(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with patch.object(
        llm_client.requests, "post", side_effect=requests.Timeout()
    ):
        text, err = llm_client._groq_one("hi", "sys", "openai/gpt-oss-120b")
    assert (text, err) == (None, "timeout")


def test_groq_no_key_skips_backend(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with patch.object(llm_client.requests, "post") as post:
        text, err = llm_client._groq_one("hi", "sys", "openai/gpt-oss-120b")
    assert (text, err) == (None, "no_key")
    post.assert_not_called()


def test_complete_aggregates_last_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with patch.object(
        llm_client.requests,
        "post",
        side_effect=[
            _http_error(429),  # groq model 1
            _http_error(429),  # groq model 2
            requests.Timeout(),  # gemini
            requests.ConnectionError(),  # ollama
        ],
    ):
        text, model = llm_client.complete("hi", "sys")
    assert (text, model) == (None, None)
    assert llm_client.last_error == "groq:http_429,groq:http_429,gemini:timeout,ollama:request_error"


def test_complete_reports_no_backend(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch.object(
        llm_client.requests, "post", side_effect=requests.ConnectionError()
    ):
        text, model = llm_client.complete("hi", "sys")
    assert (text, model) == (None, None)
    assert llm_client.last_error == "ollama:request_error"


def test_complete_clears_last_error_on_success(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    llm_client.last_error = "stale"
    resp = Mock()
    resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(llm_client.requests, "post", return_value=resp):
        text, model = llm_client.complete("hi", "sys")
    assert text == "ok"
    assert model == "openai/gpt-oss-120b"
    assert llm_client.last_error is None


def test_groq_429_body_names_limit(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    err = requests.HTTPError("429")
    err.response = Mock(
        status_code=429,
        **{
            "json.return_value": {
                "error": {
                    "message": "Rate limit reached for openai/gpt-oss-120b "
                    "in organization org-abc123 on tokens per minute (TPM): "
                    "Limit 8000, Used 7900, Requested 3100."
                }
            }
        },
    )
    with patch.object(llm_client.requests, "post", side_effect=err):
        text, tag = llm_client._groq_one("hi", "sys", "openai/gpt-oss-120b")
    assert text is None
    assert tag.startswith("http_429:Rate limit reached")
    assert "TPM" in tag and "Limit 8000" in tag
    assert "org-abc123" not in tag  # org ids are redacted


def test_complete_falls_back_to_second_groq_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    ok = Mock()
    ok.json.return_value = {"choices": [{"message": {"content": "fine"}}]}
    with patch.object(
        llm_client.requests,
        "post",
        side_effect=[_http_error(429), ok],  # 120b exhausted, llama serves
    ):
        text, model = llm_client.complete("hi", "sys")
    assert text == "fine"
    assert model == "llama-3.3-70b-versatile"
    assert llm_client.last_error is None


def test_complete_honors_model_order(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    ok = Mock()
    ok.json.return_value = {"choices": [{"message": {"content": "fine"}}]}
    with patch.object(llm_client.requests, "post", return_value=ok) as post:
        text, model = llm_client.complete(
            "hi", "sys", model_order=["llama-3.3-70b-versatile"]
        )
    assert (text, model) == ("fine", "llama-3.3-70b-versatile")
    assert post.call_args.kwargs["json"]["model"] == "llama-3.3-70b-versatile"


def test_reasoning_effort_only_for_gpt_oss(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    ok = Mock()
    ok.json.return_value = {"choices": [{"message": {"content": "fine"}}]}
    with patch.object(llm_client.requests, "post", return_value=ok) as post:
        llm_client._groq_one("hi", "sys", "openai/gpt-oss-120b")
        assert post.call_args.kwargs["json"]["reasoning_effort"] == "low"
    with patch.object(llm_client.requests, "post", return_value=ok) as post:
        llm_client._groq_one("hi", "sys", "llama-3.3-70b-versatile")
        assert "reasoning_effort" not in post.call_args.kwargs["json"]


def test_groq_models_env_override(monkeypatch):
    monkeypatch.setenv("GROQ_MODELS", "llama-3.3-70b-versatile")
    assert llm_client._groq_models() == ["llama-3.3-70b-versatile"]
    monkeypatch.delenv("GROQ_MODELS")
    assert llm_client._groq_models() == [
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
    ]
