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

---

# Deep-dive: error analysis, new-page test, freeze, review UI

**Date:** 2026-05-31
**Model under test:** `finetune_phase4_scale_500` best checkpoint (`checkpoint-1125`),
penalty-free decoding (greedy + beam-4).
**New scripts:** `predict_lines.py`, `analyze_errors.py`, `train_example_loss.py`,
`freeze_phase4.py`. One prediction pass feeds three consumers (report, loss
attribution, app Review view).

## Why the 2.5% scaling number overstates real-world performance

The Phase 4 scaling curve (50/150/500 → 90.6% / 30.0% / 2.5% CER) is measured on
the **frozen 100-line test set**, which is a *line-level* random split drawn across
the same 9 labeled pages that also supply training lines
(`data/frozen_test_set/manifest.json`). At n_train=500 the model has therefore
almost certainly seen *other lines from the same scanned page* as each test line —
same font, ink, column geometry. **2.5% is in-distribution-by-page, not
new-page generalization.** The only honest new-page number on record was the older
**17.6%** (page_0559 held out, 119 train lines) — now stale, because page_0559 sits
inside the scale_500 training pool (76 of its lines are in `splits_500.json`).

## Honest-measurement finding: the recorded 2.5% is the *tokenizer round-trip* CER

Re-scoring the frozen set against **raw ground truth** gives **4.4% CER** (beam,
greedy nearly identical — the converged model is confident: 97/100 beam==greedy),
not 2.5%. The gap is a measurement artifact, not a model change:

- The training-time `compute_metrics` computes CER between the model's prediction
  and a **tokenizer round-trip of the reference** (`batch_decode(label_ids)`), not
  the raw `.txt`. The TrOCR-base-printed tokenizer cannot represent some characters
  in the Grabar GT, so 6/100 references are silently mangled/truncated on decode.
- Those same characters are ones the model also can't emit, so dropping them from
  the reference removes **guaranteed errors from both sides**, deflating CER.
- Reproduced exactly: raw-GT greedy CER **0.0437**, round-trip greedy CER **0.0245**
  (= the recorded 2.5%). `analyze_errors.py` reports the **raw-GT** number as the
  honest one and prints both.

This is the same class of bug as the earlier jiwer fraction/percent misread and the
repetition-penalty CER distortion: the metric was measuring something subtly other
than transcription accuracy against the true text.

## Error clusters and taxonomy (frozen set, raw-GT)

Full per-line table + worst-25 contact sheet:
`reports/phase4_error_analysis_frozen.{csv,json,html}`. Overall: **4.4% beam**,
mean Armenian-letter fraction 1.00, 0 empty predictions, 99/100 distinct — **not
degenerate**.

- **By source page:** error concentrates on **page_0543 (9.0%)**; every other page
  is ≤ 3.3%, four pages ≤ 1.6%. page_0543's worst lines are the **multi-line crops**
  (one image holding two text lines) flagged in the data-prep caveat above — the
  model transcribes the first visual line and the second is counted as deletions
  (e.g. `line_058`: S4 **D31** I0).
- **By ref length:** short lines are fine; the **31+ char bin is worst (6.6%)**,
  driven by the multi-line crops (which are long by construction), not by length per se.
- **By notation:** lines with abbreviation/punctuation marks (`։ ՟ ·`) run hotter
  (4.2% vs 2.1%); letter-numeral abbreviations alone are not worse (2.2% vs 3.8%).
  The residual substitutions are overwhelmingly **confusable letters** (ղ↔ղ/ց, ո↔օ,
  ի↔ւ, case) — the LLM-recoverable kind (see Phase 5 framing).

## Per-example training-loss attribution

`train_example_loss.py` over the 500 training lines → `reports/phase4_train_example_loss.csv`
(ranked by teacher-forced CE loss). Mean loss **0.0007**; **483/500 lines fit at 0 CER**
— the model has essentially memorized its training set. The 17 nonzero-CER and
highest-loss lines are exactly the hard/suspect cases:

- **Top-2 by loss are the known multi-line crops** (`page_0559/line_024`,
  `page_0543/line_001`) — embedded `\n`, two text lines in one crop.
- Highest mean loss/CER by page: **page_0543 (0.0010 / 2.3%)** and **page_0559
  (0.0029 / 0.4%)** — the pages carrying the multi-line crops and the densest
  abbreviation/numeral notation. All other pages ≤ 0.3% train CER.

Actionable: re-slice the 3 multi-line crops in `data_prep` before the next dataset
expansion. (Influence-on-test / TracIn is a deliberate heavier follow-up, not done here.)

## Dataset freeze

`freeze_phase4.py` zips `data/{phase4_dataset,frozen_test_set,phase4_scaling}` into
`data/backups/phase4_frozen_<UTC>.zip` with an internal `SHA256SUMS`, and drops
`data/phase4_scaling/.frozen`. `build_phase4_dataset.py` now **aborts its
`shutil.rmtree` rebuild** unless `--rebuild` is passed while the experiment is frozen
— closing the footgun where a re-merge would renumber lines and silently invalidate
the `page_XXXX/line_NNN` ids in the manifest and splits.

## Prediction-review UI (read-only)

The labeling app never runs the model; it reads `data/predictions/<tag>/page_XXXX/`.
`storage.list_lines` now attaches each line's `pred` (beam) and `cer` (jiwer vs the
stored label); the new **Review view** lists crop + GT + prediction with a
char-level diff, **sorted worst-CER-first**, and the label view shows the prediction
read-only beneath the textarea (display only, never autofills). Verified on
page_0559 (mean CER 2.2% — low precisely because it is now in-pool training data).

## Honest new-page test — page_0400  ✅

page_0400 (a fresh page, in none of the 9 labeled / frozen / split pages) was
hand-labeled in the app — **71 single-line crops, 0 multi-line**, all non-empty —
then scored with the scale_500 model. Predictions were generated **after** labeling,
so the ground truth is uncontaminated by the model.

**Honest new-page CER: 1.0% beam (1.2% greedy), raw-GT.**
Report: `reports/phase4_newpage_page_0400.{csv,json,html}`. Predictions 100%
Armenian, 71/71 distinct, 0 empty — clean generalization, not degenerate.

| measurement | CER | what it answers |
|---|--:|---|
| old held-out, 119 train lines (page_0559) | 17.6% | new-page at low data → **data-volume ceiling** |
| frozen set, 500 train lines (raw-GT) | 4.4% | in-distribution-by-page, **inflated by page_0543 multi-line crops** |
| frozen set, 500 train lines (round-trip) | 2.5% | the optimistic recorded number (tokenizer artifact) |
| **new page, 500 train lines (page_0400)** | **1.0%** | **true new-page generalization** |

The new-page number being **lower than the in-distribution 4.4%** is not a paradox:
the frozen 4.4% is dragged up by page_0543's multi-line-crop deletions, while
page_0400 was cleanly sliced. With 500 training lines the **data-volume bottleneck
from the original 17.6% result is resolved** — generalization to an unseen page is
~1%.

**Error character:** 59/71 lines perfect; the 12 errors are *all* single-character
confusable-letter substitutions (Խ→ձ, լ→յ/ղ, տ→ս, փ→կ, Խ→Ե) plus one dropped space —
no dropped lines, no hallucinations. This is exactly the LLM-recoverable residual the
Phase 5 corrector is meant to absorb.

**Gate:** with honest new-page CER at 1.0% and the residual being high-context
confusable-letter substitutions, the OCR stage clears the bar for the
OCR→LLM-post-correction pipeline. The remaining catastrophic failure mode is the
multi-line crop (a data-prep slicing bug), tracked above.

## Phase 5 framing (LLM post-correction)

The end goal is OCR good enough that a frontier LLM post-corrects it to a perfect
transcription. The residual in-distribution error is dominated by **confusable-letter
substitutions** and **case** — high-context, LLM-recoverable. The **catastrophic**
errors are structural: **multi-line crops** (a whole text line dropped) and over-tall
crops (text from the next line hallucinated in). Those are *data-prep* bugs, not model
errors, and are not reliably LLM-recoverable — so the Phase 5 priority is (1) fix line
slicing, (2) feed beam-4 transcriptions + the line image context to the LLM. The
new-page CER (above) sets the realistic input-quality the Phase 5 corrector must absorb.

## Artifacts (deep-dive)

- `ml_vision/scripts/predict_lines.py`, `analyze_errors.py`, `train_example_loss.py`
- `data_prep/freeze_phase4.py`; `build_phase4_dataset.py` `--rebuild` guard
- `data/predictions/scale_500/{frozen_test_set,page_0559}/`
- `reports/phase4_error_analysis_frozen.{csv,json,html}`,
  `reports/phase4_train_example_loss.csv`
- `data/backups/phase4_frozen_<UTC>.zip`
- `labeling_ui/` Review view (storage.py + app.js + index.html + styles.css)
