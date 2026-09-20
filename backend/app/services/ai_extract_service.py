"""AI-assisted transcription of biomarker rows from raw PDF text.

The rule-based parser (parse_service) assumes the value sits right after the
biomarker name on one line. Real lab tables (e.g. the Sterling Accuris layout
in test2.pdf) print columns as Test | Result | Unit | Reference | Method,
which PyMuPDF flattens column-by-column and scrambles — hand-written regexes
cannot reassemble that reliably.

This module asks an LLM (Groq free tier, same backend as chat) to *transcribe*
each numeric row back into structured form. The LLM only copies printed facts
(test name, numeric value, unit, reference range, lab flag) — it never decides
status, never calculates, never diagnoses. Mapping a transcribed name to our
biomarker spec and low/high classification stay in deterministic code
(parse_service.match_biomarker / normalize_service / analysis_service),
exactly as before.

Anti-hallucination guards:
- every transcribed value must appear verbatim in the source chunk text,
- transcribed names are mapped to the spec by deterministic exact matching,
  never by the LLM — unmapped names are dropped,
- on any failure (no LLM backend, bad JSON, empty result) the caller falls
  back to parse_service.parse_text.
"""
import json
import logging
import os
import re

from app.services import llm_client, parse_service

logger = logging.getLogger(__name__)

# ~2k tokens per chunk: safely under the 8k TPM free-tier window even with a
# couple of sequential calls, and small enough that the model stays precise.
CHUNK_CHARS = 6000
MAX_ROWS_PER_CHUNK = 120

_SYSTEM = (
    "You are a precise medical lab data transcriber. You copy printed facts "
    "from blood report text into JSON. You never invent, round, compute, "
    "interpret, or diagnose."
)

_PROMPT_TEMPLATE = """Transcribe every biomarker result row from the lab report text below into JSON.

Rules (follow strictly):
- Output ONLY a JSON object: {{"rows": [{{"test": "...", "value": <number>, "unit": "...", "ref_low": <number or null>, "ref_high": <number or null>, "flag": "..." or null}}]}}
- One entry per numeric result row. Skip headers, footers, method names, doctor names, patient info, interpretation paragraphs, and any row without a numeric result.
- "test": the test name as printed. If it clearly matches one of these canonical names, use the canonical name exactly: {names}
- "value": the result number exactly as printed (do not round, do not convert units).
- "unit": the unit as printed (e.g. "g/dL", "mg/dL", "/cmm", "million/cmm", "%", "pg", "fL", "mmol/L", "U/L", "ng/mL", "pg/mL", "micromol/L", "IU/mL", "S/Co"). If no unit is printed, use null.
- "ref_low"/"ref_high": the printed reference range bounds as numbers. For ranges like "13.0 - 16.5" use ref_low 13.0, ref_high 16.5. For "<200" use ref_low null, ref_high 200. For ">60" use ref_low 60, ref_high null. For descriptive ranges (e.g. "Desirable: <200", "Up to 5.0", "Non Reactive: <1.0") use the numeric bound that applies. If no numeric range is printed, use null for both.
- "flag": the lab's own printed flag for the row (e.g. "H", "L", "Low", "High", "Borderline", "Normal") or null if none is printed. Never derive a flag yourself.
- The text may list columns in any order (e.g. Test, Unit, Reference, Method, Result). Read each row as a whole and associate the result number with its test correctly.
- Never invent a row that is not in the text. Never output a test you are unsure about.

Report text:
{text}
"""


def _chunk_text(text: str) -> list[str]:
    """Split on line boundaries so a chunk never cuts a row in half."""
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        current.append(line)
        size += len(line) + 1
        if size >= CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, size = [], 0
    if current:
        chunks.append("\n".join(current))
    return chunks


def _extract_json(raw: str) -> dict | None:
    """Pull the first JSON object/array out of possibly fenced model output."""
    cleaned = re.sub(r"```(?:json)?", "", raw or "").strip()
    start = min(
        (i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0),
        default=-1,
    )
    if start < 0:
        return None
    try:
        return json.loads(cleaned[start:])
    except json.JSONDecodeError:
        # Try trimming trailing junk after the last closing brace/bracket.
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _value_in_text(value: float, text: str) -> bool:
    """Anti-hallucination guard: the transcribed number must be printed."""
    compact = re.sub(r"\s+", "", text)
    for cand in (repr(value), f"{value:g}"):
        if cand in text or cand in compact:
            return True
    # Values like "< 148" print as "< 148"; also accept the digits alone.
    digits = re.sub(r"[^\d.]", "", f"{value:g}")
    return bool(digits) and digits in compact


def _to_float(raw) -> float | None:
    try:
        v = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None  # reject NaN/inf


def _validate_row(row: dict, chunk: str, spec: list[dict]) -> dict | None:
    value = _to_float(row.get("value"))
    if value is None:
        return None
    if not _value_in_text(value, chunk):
        logger.warning("AI row dropped (value not in source text): %r", row)
        return None
    bm = parse_service.match_biomarker(str(row.get("test") or ""), spec)
    if bm is None:
        return None  # name not in our spec — same as the rule parser
    unit = str(row.get("unit") or "").strip()[:24] or bm["typical_units"]
    ref_low = _to_float(row.get("ref_low"))
    ref_high = _to_float(row.get("ref_high"))
    flag_raw = str(row.get("flag") or "").strip()
    flag = None
    if flag_raw:
        low = flag_raw.lower()
        if low in ("h", "high", "+"):
            flag = "High"
        elif low in ("l", "low", "-"):
            flag = "Low"
        elif "border" in low:
            flag = "Borderline"
        elif "normal" in low:
            flag = "Normal"
        else:
            flag = flag_raw[:24]
    return {
        "biomarker_id": bm["biomarker_id"],
        "standard_name": bm["standard_name"],
        "original_name": str(row.get("test") or "").strip()[:80],
        "value": value,
        "unit": unit,
        "ref_low": ref_low,
        "ref_high": ref_high,
        "flag": flag,
    }


def _transcribe_chunk(chunk: str, spec: list[dict]) -> list[dict]:
    names = ", ".join(bm["standard_name"] for bm in spec)
    prompt = _PROMPT_TEMPLATE.format(names=names, text=chunk[: CHUNK_CHARS + 500])
    text, model = llm_client.complete(prompt, _SYSTEM, max_tokens=4096)
    if not text:
        return []
    data = _extract_json(text)
    if not data:
        logger.warning("AI extraction: unparseable JSON from %s", model)
        return []
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows[:MAX_ROWS_PER_CHUNK]:
        if not isinstance(row, dict):
            continue
        valid = _validate_row(row, chunk, spec)
        if valid is not None:
            out.append(valid)
    return out


def ai_enabled() -> bool:
    return os.environ.get("AI_EXTRACTION", "on").lower() not in (
        "0",
        "off",
        "no",
        "false",
    )


def extract(text: str, spec: list[dict]) -> tuple[list[dict], str]:
    """Extract biomarker rows, preferring AI transcription.

    Returns (rows, source) where source is "ai" or "rules". Falls back to the
    rule-based parser whenever AI is disabled, unavailable, or yields nothing.
    """
    if ai_enabled() and text and text.strip():
        try:
            merged: dict[str, dict] = {}
            for chunk in _chunk_text(text):
                for row in _transcribe_chunk(chunk, spec):
                    merged.setdefault(row["biomarker_id"], row)
            if merged:
                ordered = [
                    merged[bm["biomarker_id"]]
                    for bm in spec
                    if bm["biomarker_id"] in merged
                ]
                logger.info("AI extraction: %d biomarker(s)", len(ordered))
                return ordered, "ai"
            logger.warning("AI extraction returned no rows; using rule parser")
        except Exception:
            logger.exception("AI extraction failed; using rule parser")
    return parse_service.parse_text(text, spec), "rules"
