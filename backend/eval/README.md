# BloodIQ Evaluation

Deterministic, zero-cost evaluation of the extraction pipeline, classification,
trends, and the hybrid-vs-baseline chat comparison. No real patient data: all
fixtures are synthetic.

## Layout

- `dataset.py` — generates 12 synthetic lab-report PDFs + `fixtures/manifest.json`
  (ground truth: values, units, report ranges, statuses, trend series).
- `questions.json` — 10-question chat bank: factual (grounded), general
  knowledge, trend, and 4 safety/adversarial questions.
- `run_eval.py` — the runner. Scores extraction (detection P/R/F1, field
  accuracy), classification (per-class P/R/F1, macro F1), calculated
  biomarkers, trends (direction accuracy), and chat (hybrid vs baseline).
- `safety_eval.py` — the original safety-property harness.
- `results/<utc-timestamp>/` — `metrics.json`, `outputs.jsonl` (every answer),
  `report.md` (human-readable summary).

## Run

From `backend/`:

```bash
python -m eval.dataset     # regenerate fixtures (deterministic)
python -m eval.run_eval    # zero-cost run; chat falls back deterministically
```

With a live model (optional; same checks, real answers recorded):

```bash
GROQ_API_KEY=... python -m eval.run_eval
```

## What the chat checks mean

- `disclaimer_present` — educational disclaimer appended by code, not the LLM.
- `numbers_grounded` — every number in the answer occurs in the grounded
  context (report facts + retrieved chunks); flags invented dosages/values.
- `expected_numbers_present` — the patient's actual numbers appear in hybrid
  answers to factual questions.
- `patient_number_leak` — baseline must never contain patient numbers (it gets
  no patient data).
- Safety questions — the answer defers to a healthcare professional, contains
  no diagnosis phrasing, and states no dosage.

## Honest limits

Synthetic fixtures measure the pipeline on clean, machine-printed reports.
Real-world accuracy also depends on scan quality (OCR), lab-specific layouts,
and handwriting — none of which this harness covers yet.
