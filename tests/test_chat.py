"""Chat tests: mention detection, groundedness, hybrid/baseline, safety.

The LLM client is stubbed so no network or API key is needed.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.db import SessionLocal
from app.models.entities import Report, Result
from app.services import chat_service, llm_client
from app.utils.spec import get_biomarkers

client = TestClient(app)


@pytest.fixture()
def spec():
    return get_biomarkers()


@pytest.fixture()
def report_with_results():
    db = SessionLocal()
    report = Report(filename="chat.pdf", raw_text="Hemoglobin 11.2 g/dL (12.0-15.5)", report_date=date(2026, 9, 1))
    db.add(report)
    db.commit()
    db.refresh(report)
    db.add(
        Result(
            report_id=report.id,
            biomarker_id="BM001",
            standard_name="Hemoglobin",
            original_name="Hemoglobin",
            value=11.2,
            unit="g/dL",
            status="LOW",
            ref_low=12.0,
            ref_high=15.5,
            source="reported",
        )
    )
    db.commit()
    yield report.id
    db.query(Result).filter(Result.report_id == report.id).delete()
    db.query(Report).filter(Report.id == report.id).delete()
    db.commit()
    db.close()


@pytest.fixture()
def stub_llm(monkeypatch):
    def fake_complete(prompt, system=""):
        return ("Hemoglobin carries oxygen in red blood cells; the value 11.2 g/dL is below the report range 12.0-15.5.", "stub-model")

    monkeypatch.setattr(llm_client, "complete", fake_complete)


@pytest.fixture()
def no_llm(monkeypatch):
    monkeypatch.setattr(llm_client, "complete", lambda prompt, system="": (None, None))


# ---- mention detection ----


def test_detect_mentions_hemoglobin(spec):
    found = chat_service.detect_mentions("Why is my hemoglobin low?", spec)
    assert [b["biomarker_id"] for b in found] == ["BM001"]


def test_detect_mentions_alias(spec):
    found = chat_service.detect_mentions("What does low vit d mean?", spec)
    assert "BM038" in [b["biomarker_id"] for b in found]


def test_detect_mentions_no_false_positive(spec):
    # "Hb" as a word matches Hemoglobin; prose without biomarker terms matches nothing.
    assert chat_service.detect_mentions("What is the weather today?", spec) == []


# ---- groundedness heuristic ----


def test_numbers_grounded_true():
    ctx = "Hemoglobin: 11.2 g/dL, report range 12.0-15.5"
    assert chat_service.numbers_grounded("The value 11.2 g/dL is below 12.0.", ctx)


def test_numbers_grounded_false():
    ctx = "Hemoglobin: 11.2 g/dL, report range 12.0-15.5"
    assert not chat_service.numbers_grounded("Take 500 mg of iron daily.", ctx)


def test_numbers_grounded_no_numbers():
    assert chat_service.numbers_grounded("Hemoglobin carries oxygen.", "Hemoglobin: 11.2")


# ---- hybrid chat ----


def test_hybrid_answer_grounded(stub_llm, report_with_results):
    db = SessionLocal()
    try:
        out = chat_service.answer_question(
            "Why is my hemoglobin low?", db, report_id=report_with_results
        )
    finally:
        db.close()
    assert out["mode"] == "hybrid"
    assert out["model"] == "stub-model"
    assert "BM001" in out["used_biomarker_ids"]
    assert any(s["id"] == "kb-bio-bm001" for s in out["sources"])
    assert out["answer"].endswith(chat_service.DISCLAIMER)
    assert out["numbers_grounded"] is True


def test_hybrid_prompt_has_safety_instructions():
    prompt = chat_service.build_hybrid_prompt("q", "facts", [])
    assert "Never diagnose" in chat_service.HYBRID_SYSTEM
    assert "PATIENT DATA" in prompt


def test_hybrid_no_llm_falls_back(no_llm, report_with_results):
    db = SessionLocal()
    try:
        out = chat_service.answer_question(
            "Why is my hemoglobin low?", db, report_id=report_with_results
        )
    finally:
        db.close()
    assert out["model"] is None
    assert "unavailable" in out["answer"]
    assert out["answer"].endswith(chat_service.DISCLAIMER)
    assert "BM001" in out["used_biomarker_ids"]  # deterministic facts still attached


def test_hybrid_empty_message(report_with_results):
    db = SessionLocal()
    try:
        out = chat_service.answer_question("  ", db, report_id=report_with_results)
    finally:
        db.close()
    assert "Please ask a question" in out["answer"]


# ---- baseline ----


def test_baseline_has_no_context(stub_llm):
    out = chat_service.answer_baseline("What is hemoglobin?")
    assert out["mode"] == "baseline"
    assert out["sources"] == []
    assert out["used_biomarker_ids"] == []
    assert out["answer"].endswith(chat_service.DISCLAIMER)


def test_baseline_no_llm(no_llm):
    out = chat_service.answer_baseline("What is hemoglobin?")
    assert out["model"] is None
    assert out["answer"].endswith(chat_service.DISCLAIMER)


# ---- API ----


def test_chat_api_hybrid(stub_llm, report_with_results):
    res = client.post(
        "/api/chat",
        json={"message": "Why is my hemoglobin low?", "report_id": report_with_results},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "hybrid"
    assert data["answer"].endswith(chat_service.DISCLAIMER)


def test_chat_api_baseline(stub_llm):
    res = client.post("/api/chat/baseline", json={"message": "What is hemoglobin?"})
    assert res.status_code == 200
    assert res.json()["mode"] == "baseline"


def test_chat_api_empty_message():
    res = client.post("/api/chat", json={"message": "  "})
    assert res.status_code == 200
