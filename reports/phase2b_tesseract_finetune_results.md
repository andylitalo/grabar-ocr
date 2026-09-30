# Phase 2b — Fine-tuned hye-tesseract vs TrOCR (headline results)

**Date:** 2026-06-20 · **Raw OCR, line-level, no LLM post-correction.**
Full write-up: `docs/phase_2_alternatives.md` → "fine-tuning follow-up (2026-06-20)".
Plan: `docs/phase_2b_hye_tesseract_finetune_plan.md`.

## Question

Zero-shot `hye-calfa-n` (calfa-co/hye-tesseract) already cleared the <15% CER gate but lost to
fine-tuned TrOCR. **If we fine-tune hye-tesseract on the *same* 500-line split TrOCR scale_500 trained
on, does it match or beat TrOCR?**

## Method (apples-to-apples)

- Train set: the exact `data/phase4_scaling/splits_500.json` → `train` ids (same 500 lines, same
  empty-skip as `finetune_phase4.py`). Held-out discipline re-verified: page_0400 and the frozen set
  never enter training.
- Engine: official **tesstrain** Makefile, `START_MODEL=hye-calfa-n`, 4000 iters, LR 1e-4, PSM 13,
  90/10 internal split. CPU (M1). Output `hye-grabar.traineddata`.
- Scoring: the **unchanged** harness (`predict_lines_tesseract.py --lang hye-grabar` → `analyze_errors.py`),
  model-tag `tesseract_ft`. All three columns below report the **same `jiwer` overall beam CER** (TrOCR and
  zero-shot re-derived from their stored predictions to confirm identical metric).

## Headline results

| eval (clean, held-out) | zero-shot tesseract | **FT tesseract** | TrOCR scale_500 |
|---|---|---|---|
| frozen 100 lines | 4.9% | **3.5%** | 4.4% |
| page_0400 (71 lines, new page) | 4.6% | **1.8%** | 1.0% |

Both FT reports are healthy (arm-frac 1.00, 0 empty preds, distinct preds = n) — not degenerate.
Train BCER fell 7.4% → 1.19% monotonically (curve: `phase2b_tesseract_ft_cer_curve.csv`).

## Gate verdict

- **Primary (did fine-tuning help?): PASSED.** FT beats zero-shot on both evals (≈28% / ≈61% relative
  CER reduction).
- **Stretch (does it rival TrOCR?): PARTIAL.** FT **beats** TrOCR on the in-distribution frozen set
  (3.5% vs 4.4%) but **loses** on the genuinely new page (1.8% vs 1.0%). The two models trade wins.

## Decision: keep TrOCR as the production OCR backend (for now)

The two models are close, and which one wins depends on the eval set — but the one consistent,
decision-relevant signal is **new-page generalization** (page_0400), where TrOCR is ~1.8× lower CER.
That is the metric that matters for the thousands of unseen pages this pipeline must transcribe at
scale, so TrOCR stays in production. Reasons, ranked:

1. **Generalization to unseen pages is the production metric**, and TrOCR wins it (1.0% vs 1.8%).
   The frozen set is a line-level random split (shares pages with training) and is additionally inflated
   for TrOCR by the known page_0543 multi-line crops — so the frozen win for tesseract is the *weaker*
   signal of the two.
2. **The pipeline is already built around TrOCR** (BentoML serving, Phase 5 LLM correction tuned on its
   output). No reason to rip that out for a model that doesn't clearly win.

**But fine-tuning materially upgrades hye-tesseract's role.** It is now a near-peer, fully open,
**GPU-free, CPU-fast** model that *beats* TrOCR in-distribution and trails it only modestly on new pages —
a much stronger **fallback / ensemble cross-check** (e.g. disagreement flagging) than the zero-shot model,
and the obvious backend if the GPU/TrOCR path is ever unavailable.

## Caveats (why not over-read the gap)

- **Small eval sets** (71 / 100 lines): a sub-1-point CER gap is within plausible sampling + run-to-run
  noise. Confirming TrOCR's new-page edge wants more held-out pages, not a single decimal.
- **Frozen set is muddied** by page_0543 multi-line crops (a data-prep slicing artifact) that inflate
  TrOCR's number — so the tesseract frozen win is partly an artifact comparison, not a clean one.
- **tesstrain emitted no held-out eval-CER during training**, so checkpoint selection rode train BCER
  alone (overfit risk). The strong held-out numbers say it generalized, but a proper `lstmeval` early-stop
  (or training from `tessdata_best`) might still move the FT tesseract number.

## Artifacts

`reports/phase4_error_analysis_frozen_tesseract_ft.{csv,html}`,
`reports/phase4_newpage_page_0400_human_tesseract_ft.{csv,html}`,
`reports/phase2b_tesseract_ft_cer_curve.csv`, training log
`reports/phase2b_tesseract_ft_train.log` (gitignored). Model + tesstrain clone + scratch under the
gitignored `ml_vision/tessdata_ft/` and `ml_vision/tessdata/hye-grabar.traineddata`.
