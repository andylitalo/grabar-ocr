> ⚠️ **CORRECTION (2026-05-29) — CER values below are jiwer fractions, not percents.**
> jiwer returns a **fraction** (`1.0` = **100%** CER); any sub-100% entry mislabeled with `%`
> overstates accuracy by 100×. The qualitative decision here (all VLMs ≳ 90% CER → proceed to
> fine-tuning) is unaffected, but do not read the individual figures as literal percentages.
> Background on the same misread (which *did* invalidate Phase 3): see
> **`reports/phase_3_refinetune_results.md`**.

# Phase 2 — VLM Benchmark Results

**Date:** 2026-04-14
**Baseline (trocr-base-printed):** 93.4% CER

## CER Summary

| Model | Zero-shot CER | 5-shot CER |
|-------|:------------:|:----------:|
| `claude-sonnet-4-6` | 90.2% | 152.3% |
| `claude-haiku-4-5` | 260.7% | 121.4% |
| `gpt-5.4` | 100.0% | 100.0% |
| `gpt-5.4-mini` | 100.0% | 100.0% |
| `gemini-2.5-pro` | 100.0% | 100.0% |
| `gemini-3.1-flash` | 100.0% | 100.0% |

## Transkribus — Experiment B

| Model name | CER | Notes |
|-----------|-----|-------|
| N/A | N/A | No Armenian models in public library (checked 2026-04-25) |

## Decision

All VLM CER > 40%, no Transkribus Armenian model exists → **Proceed to Phase 3 (TrOCR fine-tuning).**
