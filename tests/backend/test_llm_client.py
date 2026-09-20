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
        text, err = llm_client._groq_complete("hi", "sys")
    assert (text, err) == (None, "http_429")


def test_groq_timeout_is_tagged(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with patch.object(
        llm_client.requests, "post", side_effect=requests.Timeout()
    ):
        text, err = llm_client._groq_complete("hi", "sys")
    assert (text, err) == (None, "timeout")


def test_groq_no_key_skips_backend(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with patch.object(llm_client.requests, "post") as post:
        text, err = llm_client._groq_complete("hi", "sys")
    assert (text, err) == (None, "no_key")
    post.assert_not_called()


def test_complete_aggregates_last_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with patch.object(
        llm_client.requests,
        "post",
        side_effect=[
            _http_error(429),  # groq
            requests.Timeout(),  # gemini
            requests.ConnectionError(),  # ollama
        ],
    ):
        text, model = llm_client.complete("hi", "sys")
    assert (text, model) == (None, None)
    assert llm_client.last_error == "groq:http_429,gemini:timeout,ollama:request_error"


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
    assert model == llm_client._groq_model()
    assert llm_client.last_error is None
