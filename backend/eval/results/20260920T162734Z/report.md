# BloodIQ Evaluation Report

Generated: 2026-09-20T16:27:34+00:00 UTC
LLM backend: hybrid=none (fallback) / baseline=none (fallback)

## 1. Extraction

- Detection P/R/F1: **1.0 / 1.0 / 1.0** (tp=25, fp=0, fn=0)
- Field accuracy (on matched detections):
  - value: **1.0**
  - unit: **1.0**
  - ref_low: **1.0**
  - ref_high: **1.0**
  - status: **1.0**

## 2. Classification

- LOW: P=1.0 R=1.0 F1=1.0 (support=5)
- NORMAL: P=1.0 R=1.0 F1=1.0 (support=14)
- HIGH: P=1.0 R=1.0 F1=1.0 (support=4)
- unknown: P=1.0 R=1.0 F1=1.0 (support=2)
- Macro F1: **1.0**

## 3. Calculated biomarkers

- Passed **1/1** checks

## 4. Trends

- Accuracy: **1.0** (3/3)
  - [PASS] BM001: expected=improving got=improving (hemoglobin 10.5 -> 11.2 -> 12.1)
  - [PASS] BM027: expected=declining got=declining (total cholesterol 240 -> 220 -> 205)
  - [PASS] BM011: expected=stable got=stable (glucose 95 -> 97 (within 5% tolerance))

## 5. Chat: hybrid vs baseline

- Hybrid disclaimer rate: 1.0
- Hybrid numbers_grounded flag rate: 1.0
- Hybrid expected-numbers-present rate: 1.0
- Hybrid safety: deferral=1.0, no-diagnosis=1.0, no-invented-dosage=1.0
- Baseline disclaimer rate: 1.0
- Baseline patient-number leaks: 0

Full per-question answers: outputs.jsonl
