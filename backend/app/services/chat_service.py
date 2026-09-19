"""Conversational layer: hybrid (deterministic + RAG + LLM) and LLM-only baseline.

Hybrid pipeline (the BloodIQ architecture under evaluation):
  1. Detect which biomarkers the question mentions (alias matching).
  2. Pull deterministic patient facts: the user's own results (value, unit,
     report-specific range, status) and trend direction for those biomarkers.
  3. Retrieve curated knowledge chunks (RAG) for the question.
  4. Ask the LLM to answer using ONLY that grounded context, with a strict
     safety system prompt. Numbers in the answer are checked against the
     context afterwards (groundedness signal, not a gate).

Baseline pipeline (for the research comparison): the raw question goes
straight to the LLM with no patient data and no retrieval.

Both modes append the educational disclaimer deterministically, so it never
depends on the model complying.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.entities import Report
from app.services import llm_client, retrieval_service, trend_service
from app.utils.spec import get_biomarkers

DISCLAIMER = (
    "BloodIQ is educational and is not a substitute for professional medical "
    "advice. Always consult a qualified healthcare professional about your "
    "lab results."
)

HYBRID_SYSTEM = (
    "You are BloodIQ's educational assistant. Answer the user's question "
    "using ONLY the PATIENT DATA and KNOWLEDGE excerpts provided below. "
    "Use the exact numbers from that context; do not invent or round new "
    "numbers, and do not bring in outside medical knowledge beyond what the "
    "excerpts state. If the context does not contain the answer, say so "
    "instead of guessing. "
    "Never diagnose conditions, prescribe medication, recommend treatments "
    "or dosages, or give emergency guidance. If asked for any of these, "
    "decline that specific request and give general educational information "
    "instead, advising the user to consult a healthcare professional. "
    "Keep the answer concise and non-alarming."
)

BASELINE_SYSTEM = (
    "You are a helpful assistant answering questions about blood test "
    "biomarkers. This is educational information, not medical advice. Never "
    "diagnose conditions, prescribe medication, or recommend treatments; "
    "advise the user to consult a healthcare professional."
)

_FALLBACK_NO_LLM = (
    "The AI backend is unavailable right now (no GROQ_API_KEY and no local "
    "Ollama server). Below are your deterministic results and the curated "
    "knowledge excerpts that were retrieved for your question."
)

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def detect_mentions(message: str, biomarkers: list[dict] | None = None) -> list[dict]:
    """Biomarkers mentioned in *message*, via alias/standard-name matching.

    Aliases are tried longest-first so 'RDW-SD' wins over 'RDW'; matching is
    case-insensitive on word boundaries so 'Hb' doesn't match 'Rhabdo'.
    """
    biomarkers = biomarkers if biomarkers is not None else get_biomarkers()
    found: list[dict] = []
    seen: set[str] = set()
    for b in biomarkers:
        if b["biomarker_id"] in seen:
            continue
        names = [b["standard_name"], *b.get("common_aliases", [])]
        for name in sorted(set(names), key=len, reverse=True):
            if not name or len(name.strip()) < 2:
                continue
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", message, re.IGNORECASE):
                found.append(b)
                seen.add(b["biomarker_id"])
                break
    return found


def _patient_facts(
    db: Session, report_id: int | None, mentioned: list[dict]
) -> tuple[str, list[str]]:
    """Deterministic facts block + the biomarker ids it covers."""
    if report_id is None:
        return "No report selected; no patient data available.", []
    report = db.get(Report, report_id)
    if report is None or not report.results:
        return "The selected report has no analyzed results yet.", []

    mentioned_ids = {b["biomarker_id"] for b in mentioned}
    if mentioned_ids:
        rows = [r for r in report.results if r.biomarker_id in mentioned_ids]
    else:
        rows = [r for r in report.results if r.status in ("LOW", "HIGH")][:8]
    if not rows:
        return "The selected report has no matching or abnormal results.", []

    lines = []
    used_ids = []
    for r in rows:
        lo, hi = r.ref_low, r.ref_high
        ref = f"{lo}-{hi}" if lo is not None and hi is not None else "not on report"
        calc = " [calculated]" if r.source == "calculated" else ""
        lines.append(
            f"- {r.standard_name} (as reported: {r.original_name}): {r.value} "
            f"{r.unit}, report range {ref}, status {r.status}{calc}"
        )
        used_ids.append(r.biomarker_id)

    for b in mentioned:
        trend = trend_service.get_trend(db, b["biomarker_id"])
        if trend and len(trend["points"]) >= 2:
            latest = trend["points"][-1]
            lines.append(
                f"- Trend for {trend['standard_name']}: {trend['direction']} "
                f"across {len(trend['points'])} reports "
                f"(latest {latest['value']} {latest['unit']} "
                f"on {latest['report_date']})"
            )
    return "\n".join(lines), used_ids


def build_hybrid_prompt(
    message: str,
    patient_facts: str,
    hits: list[retrieval_service.Hit],
    history: list[dict] | None = None,
) -> str:
    parts = []
    if history:
        convo = "\n".join(
            f"{'User' if m.get('role') == 'user' else 'Assistant'}: "
            f"{m.get('content', '')}"
            for m in history[-6:]
        )
        parts.append(f"CONVERSATION SO FAR:\n{convo}")
    parts.append(f"PATIENT DATA (deterministic, from the user's own reports):\n{patient_facts}")
    if hits:
        kb = "\n\n".join(f"[{h.chunk.id}] {h.chunk.title}:\n{h.chunk.text}" for h in hits)
        parts.append(f"KNOWLEDGE EXCERPTS (curated):\n{kb}")
    parts.append(f"USER QUESTION: {message}")
    return "\n\n".join(parts)


def numbers_grounded(answer: str, context: str) -> bool:
    """Heuristic: every number in the answer must occur in the context.

    Compares numeric values (not strings) so '11.20' matches '11.2'.
    Returns True when the answer contains no numbers at all.
    """
    ctx_numbers = {round(float(n), 6) for n in _NUMBER_RE.findall(context)}
    return all(round(float(n), 6) in ctx_numbers for n in _NUMBER_RE.findall(answer))


def answer_question(
    message: str,
    db: Session,
    report_id: int | None = None,
    history: list[dict] | None = None,
) -> dict:
    """Hybrid grounded answer. Never raises for missing LLM (falls back)."""
    if not message.strip():
        return {
            "answer": "Please ask a question about your blood reports.",
            "model": None,
            "mode": "hybrid",
            "sources": [],
            "used_biomarker_ids": [],
            "numbers_grounded": True,
        }
    spec = get_biomarkers()
    mentioned = detect_mentions(message, spec)
    patient_facts, used_ids = _patient_facts(db, report_id, mentioned)

    query = message + " " + " ".join(b["standard_name"] for b in mentioned)
    hits = retrieval_service.retrieve(query, top_k=4)

    prompt = build_hybrid_prompt(message, patient_facts, hits, history)
    text, model = llm_client.complete(prompt, HYBRID_SYSTEM)
    if text is None:
        kb_part = (
            "\n\nRetrieved knowledge:\n"
            + "\n".join(f"- [{h.chunk.id}] {h.chunk.title}" for h in hits)
            if hits
            else ""
        )
        text = f"{_FALLBACK_NO_LLM}\n\n{patient_facts}{kb_part}"

    answer = f"{text.strip()}\n\n{DISCLAIMER}"
    return {
        "answer": answer,
        "model": model,
        "mode": "hybrid",
        "sources": [{"id": h.chunk.id, "title": h.chunk.title} for h in hits],
        "used_biomarker_ids": used_ids,
        "numbers_grounded": numbers_grounded(text, prompt),
    }


def answer_baseline(message: str) -> dict:
    """LLM-only baseline: no patient data, no retrieval. For comparison."""
    if not message.strip():
        return {
            "answer": "Please ask a question.",
            "model": None,
            "mode": "baseline",
            "sources": [],
            "used_biomarker_ids": [],
            "numbers_grounded": True,
        }
    text, model = llm_client.complete(message, BASELINE_SYSTEM)
    if text is None:
        text = (
            "The AI backend is unavailable right now (no GROQ_API_KEY and no "
            "local Ollama server)."
        )
    return {
        "answer": f"{text.strip()}\n\n{DISCLAIMER}",
        "model": model,
        "mode": "baseline",
        "sources": [],
        "used_biomarker_ids": [],
        "numbers_grounded": True,  # vacuous: no context was provided
    }
