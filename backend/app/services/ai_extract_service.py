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
- a chunk that fails even after long-backoff retries is parsed with
  parse_service.parse_text for that chunk only, so a rate-limited chunk never
  silently drops its rows; the whole-text rule fallback applies only when AI
  yields nothing at all.
"""
import json
import logging
import os
import re
import time

from app.services import llm_client, parse_service

logger = logging.getLogger(__name__)

# ~2k tokens per chunk: small enough that the model stays precise.
CHUNK_CHARS = 6000
MAX_ROWS_PER_CHUNK = 120
# Pacing between chunk calls keeps a long report under the free-tier
# tokens-per-minute budget instead of bursting all chunks at once.
# ~3k input+output tokens per chunk / 30s ~= 6k TPM, inside the 8k window.
CHUNK_DELAY_SECONDS = 30
# Output rarely exceeds a few hundred tokens (~15 rows per chunk); 1024 leaves
# headroom while keeping the TPM burn of each call low.
EXTRACTION_MAX_TOKENS = 1024
# Rate-limited chunks are retried with long backoff: Groq's TPM window resets
# within a minute, so waiting it out almost always recovers the chunk. A hard
# daily-quota 429 just burns these retries, then the chunk falls back to the
# rule parser below.
_CHUNK_RETRY_DELAYS = (30, 60, 120)

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
- "ref_low"/"ref_high": the printed reference range bounds as numbers. For ranges like "13.0 - 16.5" use ref_low 13.0, ref_high 16.5. For "<200" use ref_low null, ref_high 200. For ">60" use ref_low 60, ref_high null. For descriptive ranges (e.g. "Desirable: <200", "Up to 5.0", "Non Reactive: <1.0") use the numeric bound that applies. If a range is printed as multiple bands (e.g. "Deficiency: <10 / Insufficiency: 10-30 / Sufficiency: 30-100"), use the outermost normal/sufficiency band (here ref_low 30, ref_high 100). If no numeric range is printed, use null for both.
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
        # Values may print with a comparison operator ("< 148"); keep digits.
        v = float(re.sub(r"[<>\u2264\u2265~=\s]", "", str(raw).replace(",", "")))
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None  # reject NaN/inf


# Units the model spells out that we normalize to the spec's printed form.
_UNIT_ALIASES = {
    "micro g/dl": "\u00b5g/dL",
    "microg/dl": "\u00b5g/dL",
    "ug/dl": "\u00b5g/dL",
    "uiu/ml": "\u00b5IU/mL",
    "micromol/l": "\u00b5mol/L",
}


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
    unit = _UNIT_ALIASES.get(unit.lower(), unit)
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


def _complete_with_retry(prompt: str, retry: bool) -> tuple[str | None, str | None]:
    """Call the LLM, retrying silent failures (incl. TPM rate limits).

    The client surfaces every backend failure as (None, None), so retries are
    bounded and back off long enough for the per-minute token window to reset.
    With retry=False a single attempt is made (used once an earlier chunk has
    already proven the backend unreachable — the remaining chunks then fail
    fast instead of each burning minutes of backoff).
    """
    delays = (0,) + _CHUNK_RETRY_DELAYS if retry else (0,)
    for attempt, wait in enumerate(delays):
        if wait:
            logger.warning(
                "AI extraction: chunk attempt %d failed; retrying in %ds",
                attempt,
                wait,
            )
            time.sleep(wait)
        text, model = llm_client.complete(
            prompt, _SYSTEM, max_tokens=EXTRACTION_MAX_TOKENS
        )
        if text:
            return text, model
    return None, None


def _transcribe_chunk(
    chunk: str, spec: list[dict], retry: bool = True
) -> tuple[list[dict], bool]:
    """Transcribe one chunk. Returns (rows, failed).

    failed=True means the chunk could not be transcribed even after retries;
    the caller falls back to the rule parser for that chunk so its rows are
    never silently dropped.
    """
    names = ", ".join(bm["standard_name"] for bm in spec)
    prompt = _PROMPT_TEMPLATE.format(names=names, text=chunk[: CHUNK_CHARS + 500])
    text, model = _complete_with_retry(prompt, retry)
    if not text:
        logger.warning("AI extraction: chunk failed after retries")
        return [], True
    data = _extract_json(text)
    if not data:
        logger.warning("AI extraction: unparseable JSON from %s", model)
        return [], True
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return [], True
    out: list[dict] = []
    for row in rows[:MAX_ROWS_PER_CHUNK]:
        if not isinstance(row, dict):
            continue
        valid = _validate_row(row, chunk, spec)
        if valid is not None:
            out.append(valid)
    return out, False


def ai_enabled() -> bool:
    return os.environ.get("AI_EXTRACTION", "on").lower() not in (
        "0",
        "off",
        "no",
        "false",
    )


def extract(text: str, spec: list[dict]) -> tuple[list[dict], str]:
    """Extract biomarker rows, preferring AI transcription.

    Returns (rows, source) where source is "ai" or "rules". Every chunk is
    transcribed by the LLM; a chunk that still fails after retries is parsed
    with the deterministic rule parser instead, so a rate-limited chunk can
    never silently drop its rows. The whole-text rule fallback is used only
    when AI is disabled, unavailable for every chunk, or yields nothing at all.
    """
    if ai_enabled() and text and text.strip():
        try:
            merged: dict[str, dict] = {}
            ai_rows = 0
            failed_chunks = 0
            retry = True
            chunks = _chunk_text(text)
            for i, chunk in enumerate(chunks):
                if i:
                    time.sleep(CHUNK_DELAY_SECONDS)
                rows, failed = _transcribe_chunk(chunk, spec, retry=retry)
                if failed:
                    failed_chunks += 1
                    # The backend already proved unreachable for one chunk;
                    # don't burn minutes of backoff on every remaining one.
                    retry = False
                    for row in parse_service.parse_text(chunk, spec):
                        merged.setdefault(row["biomarker_id"], row)
                    continue
                for row in rows:
                    if row["biomarker_id"] not in merged:
                        merged[row["biomarker_id"]] = row
                        ai_rows += 1
            if merged:
                if failed_chunks:
                    logger.warning(
                        "AI extraction: %d/%d chunk(s) failed after retries; "
                        "rule parser covered those chunks",
                        failed_chunks,
                        len(chunks),
                    )
                ordered = [
                    merged[bm["biomarker_id"]]
                    for bm in spec
                    if bm["biomarker_id"] in merged
                ]
                logger.info("AI extraction: %d biomarker(s)", len(ordered))
                return ordered, "ai" if ai_rows else "rules"
            logger.warning("AI extraction returned no rows; using rule parser")
        except Exception:
            logger.exception("AI extraction failed; using rule parser")
    return parse_service.parse_text(text, spec), "rules"
