# BloodIQ 🩸

A full-stack blood-report analytics app: upload a blood-test PDF → extract text
with PyMuPDF → find lab results **with the reference ranges printed on that
report** → normalize to the 45-biomarker spec → flag LOW / NORMAL / HIGH /
unknown → optional AI explanation → trend charts → simple web UI.

Built at **zero cost**: every library is free and open source; AI and hosting
use free tiers only (and the app works without them).

> **Source of truth.** The biomarker spec lives in
> `data/biomarkers/BloodIQ_Biomarker_Specification_v2.xlsx`. The JSON the app
> serves (`data/biomarkers/biomarkers.json`) is regenerated from it — never edit
> the JSON by hand:
>
> ```bash
> python backend/app/utils/import_spec.py   # from the project root
> ```
>
> **Reference ranges:** BloodIQ uses *only* the range printed on each lab
> report. There are no universal hard-coded ranges anywhere in the code or the
> spec — when a report omits the range, the result's status is `unknown`.

## Prerequisites

- Python 3.11+ (check with `python3 --version`)
- (Optional) Docker — only for the Postgres database (SQLite works with zero setup)
- (Optional) [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — only if
  you need to read scanned/image-only PDFs
- (Optional) [Ollama](https://ollama.com) — only for free offline AI explanations

## Quick start

From the project root (`bloodiq/`):

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd backend
uvicorn app.main:app --reload
```

Or without changing directory:

```bash
PYTHONPATH=backend uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 in your browser. The API docs are at
http://127.0.0.1:8000/docs.

> The code runs as the `app` package from inside `backend/` — both commands
> above work because `backend/app/utils/paths.py` resolves the project root
> (parent of `backend/`) for the SQLite file, uploads, and frontend, regardless
> of where you start the server.

## How it works

1. **Upload** — `POST /api/reports/upload` saves the PDF to `data/sample_reports/`,
   extracts its text with PyMuPDF (`doc.page.get_text()`), and captures the
   report date from the text (formats like `MM/DD/YYYY`, `YYYY-MM-DD`,
   `Jan 15, 2026`, `15-Jan-2026`, `Report Date: ...`, `Collected: ...`;
   falls back to the upload date). Pages with no extractable text are flagged
   as scanned (OCR is an optional, clearly-marked hook in
   `backend/app/services/pdf_service.py`).
2. **Parse** — `backend/app/services/parse_service.py` matches the spec's
   standard names + aliases (longest first, so "Total Cholesterol" beats
   "Cholesterol"; hyphen-aware boundaries so "hs-CRP" never merges into "CRP")
   against the text, captures values (thousands commas handled), the unit, and
   the reference range printed on the report (`(12.0-15.5)`, `Ref 4,000-11,000`,
   `> 60`, `< 200`).
3. **Normalize** — `backend/app/services/normalize_service.py` maps each result
   to its `biomarker_id` (e.g. `BM001`) while keeping the original test name as
   written in the report. Subtype no-merge rules are enforced (RDW-CV vs RDW-SD,
   vitamin D analytes, total vs ionized calcium, CRP vs hs-CRP, serum vs RBC
   folate). Non-HDL cholesterol (BM031) and transferrin saturation (BM037) are
   derived from their inputs when reported values are absent and units are
   compatible — every result carries `source: "reported" | "calculated"`.
4. **Analyze** — each value is compared to its *report-specific* reference range
   → `LOW` / `NORMAL` / `HIGH`, or `unknown` when the report printed no range.
   Stored in the database with a rule-based summary.
5. **Trends** — `GET /api/reports/trends/{biomarker_id}` aligns a biomarker's
   results across report dates and returns `improving` / `declining` / `stable`
   (5% tolerance band), excluding points with incompatible units.
6. **Explain (optional)** — `POST /api/reports/{id}/analyze` also tries an AI
   explanation: Google Gemini (free tier, needs `GEMINI_API_KEY`) → local Ollama
   → falls back to the rule-based summary. Never required.
7. **View** — the static frontend (`frontend/`, no build step) shows a results
   table with the report's reference range, status pills, `HGB → Hemoglobin`
   traceability, `calculated` badges, a canvas trend chart, and the AI panel.

## Database

Two paths, selected by `DATABASE_URL`:

| Setup | Command |
|---|---|
| **SQLite (zero-setup default)** | just run the app — uses `data/bloodiq.db` |
| **Postgres (pgvector image)** | `docker compose up -d`, then run with `DATABASE_URL=postgresql://bloodiq:bloodiq@localhost:5432/bloodiq` |

`docker-compose.yml` starts `pgvector/pgvector:pg16` (service `db`, database/user
`bloodiq`, port 5432, named volume). The pgvector extension is there for the
future RAG knowledge base; the app itself works identically on either database.

## API reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | `{"status": "ok"}` |
| GET | `/api/biomarkers` | Full 45-biomarker spec (from the xlsx) |
| POST | `/api/reports/upload` | Multipart PDF → `{report_id, filename, report_date, text_preview, pages, note}` |
| POST | `/api/reports/{id}/analyze` | Parse + normalize + analyze → results, summary, `ai_explanation` (may be null) |
| GET | `/api/reports` | List reports with result counts and report dates |
| GET | `/api/reports/trends/{biomarker_id}` | Trend points + `improving`/`declining`/`stable` (register before `/{report_id}`) |
| GET | `/api/reports/{id}` | Full report detail including results |
| POST | `/api/chat` | Hybrid grounded chat: `{message, report_id?, history?}` → `{answer, model, mode, sources, used_biomarker_ids, numbers_grounded}` |
| POST | `/api/chat/baseline` | LLM-only baseline (no patient data, no RAG) — for the research comparison |

## Running the tests

```bash
pip install -r requirements.txt
python -m pytest
```

- `tests/test_parser.py` — reference-range extraction (parenthesized, `Ref`-prefixed,
  thousands commas, open-ended), `unknown` status without a range, alias →
  `biomarker_id` mapping with original-name preservation, subtype no-merge rules,
  Non-HDL / transferrin-saturation calculated-vs-reported with `source`.
- `tests/test_trend.py` — trend direction (improving/declining/stable, 2-point
  rule, 5% tolerance) and incompatible-unit exclusion.
- `tests/test_api.py` — full upload → analyze flow against a generated PDF
  (report date capture, LOW status from the report's range, calculated Non-HDL)
  plus the trends endpoint.
- `tests/test_retrieval.py` — KB chunk loading (45 biomarker + 6 general
  chunks) and TF-IDF ranking.
- `tests/test_chat.py` — biomarker mention detection, the `numbers_grounded`
  heuristic, hybrid chat (grounded answer, sources, deterministic disclaimer,
  no-LLM fallback), the LLM-only baseline, and the chat API endpoints.

## Conversational AI (hybrid RAG + chat)

**Knowledge base** — `data/knowledge/` holds 51 curated chunks: one per
biomarker generated from the official spec (`python -m backend.app.utils.build_kb`)
plus 6 hand-written general chunks (classification, reference ranges, trends,
calculated results, traceability, safety). No LLM-generated medical claims.

**Retrieval** — TF-IDF cosine similarity (`backend/app/services/retrieval_service.py`):
deterministic, zero-cost, no model download. Swappable for embeddings later via
the `Retriever` protocol (pgvector is provisioned in `docker-compose.yml`).

**Hybrid chat** (`POST /api/chat`) — detects mentioned biomarkers → pulls your
deterministic results + trend direction → retrieves KB chunks → asks the LLM
(Gemini free tier → local Ollama) to answer using *only* that context, with a
strict safety system prompt. Every answer gets the educational disclaimer
appended in code, and `numbers_grounded` flags any number not present in the
context. Works without an LLM too (deterministic fallback listing your facts).

**Baseline** (`POST /api/chat/baseline`) — the raw question straight to the LLM,
no patient data, no retrieval. This is the LLM-only arm of the research
comparison; toggle Hybrid/Baseline in the frontend chat panel.

**Safety eval** — `cd backend && ../.venv/bin/python -m eval.safety_eval`
runs adversarial prompts (diagnosis/treatment/emergency/prompt-injection)
against the deterministic guarantees: safety instructions, disclaimer, and the
groundedness signal.

## AI explanations (optional, free)

**Option A — Google Gemini (free tier):**
```bash
export GEMINI_API_KEY="your-key-here"   # get one free at https://aistudio.google.com
cd backend && uvicorn app.main:app --reload
```

**Option B — Ollama (fully local, offline):**
```bash
ollama pull llama3.1
ollama serve
# then start BloodIQ in another terminal
```

Without either, `ai_explanation` comes back `null` and the UI says so — the
rule-based summary still works.

## Deployment (free tiers)

**Render** — the repo includes `render.yaml`. Push to GitHub, create a new Web
Service from the repo, Render reads `render.yaml` automatically (free plan).
Add `GEMINI_API_KEY` in the dashboard's environment variables if you want AI.

**Hugging Face Spaces** — create a Space with the *Docker* SDK, push this repo,
and it builds from the included `Dockerfile` (serves on port 7860). Add
`GEMINI_API_KEY` as a Space secret for AI explanations.

> Note: Render's free tier sleeps after inactivity (first request wakes it, slowly).
> Both options are fine for a demo/final project, not for real clinical traffic.

## Safety disclaimer

BloodIQ is educational and is **not a substitute for professional medical
advice**. It does not diagnose, prescribe, or replace a healthcare
professional. Reference ranges shown are the ones printed on each lab report —
they vary by laboratory, age, sex, and individual health conditions, so always
confirm with your report and consult a qualified healthcare professional.

## Not yet built (doc roadmap follow-ups)

Per the project docs, these remain future work:

- Full evaluation dataset (extraction accuracy, classification metrics, trend
  accuracy, explanation factuality/clarity) — the chat comparison harness and
  safety eval are the starting point
- Embedding-based retrieval (MiniLM + pgvector) as an upgrade over TF-IDF
- Research paper
- React + Recharts frontend migration (the current canvas trend chart is interim)
