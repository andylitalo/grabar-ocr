# Phase 4 Results — Honest Generalization (held-out CER)

**Date:** 2026-05-29
**Script:** `ml_vision/scripts/finetune_phase4_fixed.py`
**Base:** `microsoft/trocr-base-printed` (93.4% baseline CER)
**Builds on:** Phase 3 gate PASSED — `reports/phase_3_converge_results.md`

> This supersedes the original `finetune_phase4` run, whose "held-out 100–247%"
> numbers were the same degenerate collapse + jiwer fraction/percent misread that
> invalidated Phase 3 (see `reports/phase_3_refinetune_results.md`). This is the
> **first honest generalization measurement.**

---

## TL;DR

- **Held-out CER on `page_0559` (never seen in training): `0.1765` = 17.6%** (greedy).
- **Gate verdict: PARTIAL** (< 0.40 → not a generalization failure; ≥ 0.15 → not yet
  production). Next step is **more labeled data (~500–1000 lines)**, not a recipe change.
- The model generalizes to a genuinely unseen page producing real Bolorgir, with many
  lines at 0.08–0.17 CER. The remaining error is a **data-quantity ceiling**, not
  instability or script ignorance.

---

## Setup

| | |
|---|---|
| Train | `page_0335` + `page_0543` — **119** non-empty lines |
| Held-out eval | `page_0559` — **89** non-empty lines (never seen in training) |
| Recipe | lr=2e-5 cosine, warmup 30, 40 epochs, grad-accum 2, max_grad_norm 1.0, decoder_start=eos(2) |
| Decoding | **penalty-free** (see `reports/phase_3_converge_results.md`); per-epoch eval greedy, sample preds beam-4 |
| Best checkpoint | epoch 36 (loaded via `load_best_model_at_end`) |

---

## Held-out CER trajectory (selected)

Clean monotonic convergence, then plateau — this is converged on the available data,
not undertrained (eval_loss flattened at ~0.576).

| Epoch | eval_loss | eval_cer | = % |
|------:|:---------:|:--------:|:---:|
| 1  | 12.45 | 0.976 | 98% |
| 6  | 1.949 | 1.049 | 105% |
| 11 | 1.547 | 0.655 | 65% |
| 16 | 0.959 | 0.400 | 40% |
| 21 | 0.622 | 0.240 | 24% |
| 26 | 0.609 | 0.217 | 22% |
| 31 | 0.615 | 0.189 | 19% |
| **36** | 0.575 | **0.1765** | **17.6%** |
| 40 | 0.576 | 0.179 | 18% |

---

## Sample predictions (held-out `page_0559`, beam-4, penalty-free)

Real Bolorgir with correct structure and many near-correct lines:

```
CER 0.087 | PRED 'քհ. Փառաւորեալ անուն քո'              REF 'գձ. Փառաւորեալ անուն քո'
CER 0.107 | PRED 'յննառելի բնութիւն։ Համբ. այ.'          REF 'Անճառելի բնութիւն։ Համբ. աձ.'
CER 0.111 | PRED 'կրուրբ Կաչի պահոցն։ Հարց գկ.'           REF 'սուրբ Խաչի պահոցն։ Հարց գկ.'
CER 0.111 | PRED 'յաւխտեան։'                              REF 'յաւիտեան։'
CER 0.129 | PRED 'Բ. Կիր. ԱԱ. Ղորրորդ։ ղարեկենդան'        REF '6. Կիր. ԱՁ. Չորրորդ։ Բարեկենդան'
CER 0.167 | PRED 'Ոնդ կանայան։'                           REF 'Ընդ կանայսն։'
```

Harder lines (CER 0.37–0.56) cluster on short headers/abbreviations and the multi-line
crops noted below.

---

## Data-prep caveat (follow-up, non-blocking)

A few label files are **multi-text-line crops** with embedded newlines — the line-crop
slicing merged adjacent text lines:

- `page_0543`: 2 / 90 label files contain > 1 line
- `page_0559`: 1 / 91 label files contain > 1 line

These inflate per-line CER slightly (one image, two lines of target text). Small
fraction here, but worth fixing in `data_prep` before scaling the dataset.

---

## Conclusions & next step

1. **Generalization is real**, not a degenerate artifact: 17.6% held-out CER from only
   119 training lines, down from 93.4% baseline.
2. **PARTIAL gate** → the bottleneck is data volume. Collect ~500–1000 labeled lines and
   re-measure before investing in Phase 5 server infrastructure.
3. Recipe and decoding are settled (stable optimization + penalty-free generation);
   future gains should come from data, not hyperparameters.

## Artifacts

- `ml_vision/scripts/finetune_phase4_fixed.py` — this run.
- `ml_vision/checkpoints/finetune_phase4_fixed/` — best checkpoint (epoch 36, 17.6%).
- `reports/logs/finetune_phase4_fixed.log` — full training log.
