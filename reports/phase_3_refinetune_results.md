# Phase 3 Re-Investigation — Fine-Tuning Never Actually Worked (and the fix)

**Date:** 2026-05-29
**Author:** debugging session triggered by "we got poor results training on the new pages"
**Baseline (`trocr-base-printed`, no fine-tuning):** 93.4% CER

---

## TL;DR

1. **The headline results in `phase_3_results.md` and `phase_2_vlm_results.md` are wrong** — they
   report jiwer's raw CER *fraction* as a *percentage*. jiwer returns `1.0` for 100% CER, so the
   celebrated **"1.0% CER"** was actually **100% CER**. Fine-tuning never worked.
2. The trained checkpoints (`finetune_poc`, `finetune_phase4`) are **degenerate** — they emit a
   single repeated space token for every image, including their own training data (confirmed by
   teacher-forced forward pass: loss ~4.6, argmax = all spaces).
3. **Root cause: training instability**, not data or generalization. At `lr=5e-5` the loss
   oscillated (3↔11) with grad norms of 300–900 — the optimizer diverged into a degenerate minimum.
4. **A stabilized re-run works in kind:** `lr=1e-5` + grad-accum + grad-clip produces smooth
   monotonic loss descent and, for the first time, **real Armenian Bolorgir output** with correct
   line length and word boundaries. Train-set CER dropped **93.4% → 65.7%**.
5. It is **not done** — 65.7% is undertrained (LR decayed to ~0 while loss was still falling). But
   the failure mode is now character precision + repetition, not script ignorance. The path is clear.

---

## How the metric was misread

`jiwer.cer` returns `(S + D + I) / N` as a **fraction**: `1.0` = 100% CER, `3.0` = 300% CER
(possible when insertions exceed reference length). The Phase 3 report appended `%` to the raw
fraction. Real values, read straight from the trainer logs:

| Epoch | Logged `eval_cer` | Report wrote | Actually is |
|------:|:-----------------:|:------------:|:-----------:|
| 1     | 1.8177            | "181.8%"     | 181.8%      |
| 7     | 3.0342            | **"3.03%"**  | **303.4%**  |
| 16    | 1.0000            | **"1.0%"**   | **100.0%**  |

The same error inflates Phase 2's VLM table (sub-100% entries are suspect) and Phase 4's
`finetune_phase4` "held-out 100–247%" run (the same blank/garbage collapse, honestly unreported).

## Evidence the checkpoints are degenerate

Loading `finetune_poc/checkpoint-144` (the claimed-best "1.0%" model) and generating on its **own
training page** (`page_0335`):

- 34/34 predictions identical and empty (only the space token `1437`).
- 0% Armenian characters produced.
- Teacher-forced forward pass on a training line: loss **4.58**, argmax token = `1437` (space) at
  every position. The decoder learned nothing; it sits in the "always predict the most common
  token" minimum (which alone drops loss ~10 → ~3, explaining the plateau the report mistook for
  success).

`finetune_phase4/checkpoint-180` behaves identically on both train (`page_0543`) and held-out
(`page_0559`) pages → this was never a generalization failure.

## Root cause: optimizer divergence

| Run | LR | Schedule | Loss behaviour | grad_norm | Outcome |
|-----|----|----------|----------------|-----------|---------|
| original (`finetune_poc`, `finetune_phase4`) | 5e-5 | linear | oscillates 3↔11, sometimes **increases** | 300–900 | collapse → space/garbage, CER ≥ 100% |
| stabilized (`finetune_lowlr`) | 1e-5 | linear + warmup 30, grad-accum 2, clip 1.0 | **monotonic** 30 → 1.0 | 10–110 | learns script, CER 65.7% |

A secondary config bug was also corrected (`decoder_start_token_id` was overridden to `cls`=0
instead of TrOCR's canonical `</s>`=2); on its own it only changed the failure *mode*
(blank → garbage). The instability was the dominant cause.

---

## Stabilized run — results (`ml_vision/scripts/finetune_lowlr.py`)

- Train = eval = `page_0335` (34 lines), overfit proof-of-concept.
- Best checkpoint: `ml_vision/checkpoints/finetune_lowlr/checkpoint-195` (epoch 39).
- **Best train-set CER: 0.657 (65.7%)** — vs 93.4% baseline, vs 100% for every prior checkpoint.

### CER trajectory (selected; full in trainer logs)

| Epoch | eval_loss | eval_cer | = % |
|------:|:---------:|:--------:|:---:|
| 1  | 15.89 | 0.927 | 93%  |
| 9  | 2.43  | 1.399 | 140% |
| 18 | 1.55  | 0.892 | 89%  |
| 27 | 1.245 | 0.771 | 77%  |
| 34 | 1.079 | 0.694 | 69%  |
| 39 | 1.024 | **0.657** | **66%** |
| 40 | 1.021 | 0.661 | 66%  |

Loss was **still descending at epoch 40** while the LR schedule had decayed to ~0 → the model was
cut off mid-improvement (undertrained, not converged).

### Sample predictions (the qualitative leap)

```
CER 0.54 | PRED 'Ուաաիցից աաաաաաաաաաաացա-'   REF 'Ուսուցից անօրինաց զճանա-'
CER 0.64 | PRED 'պարս ասսս, աարսաս աք'        REF 'պարհս քո, եւ ամպարիշտք'
CER 0.63 | PRED 'Տէր, եեեեր եերիի իիիի ու-'    REF 'Տէր, եթէ զշրթունս իմ բա-'
```

For the first time the model emits **Armenian Bolorgir**, with correct line length, leading
characters, word boundaries, and trailing hyphenation. The remaining errors are **character
imprecision and token repetition** (`աաաա`, `եեեե`) — a classic undertrained / no-repetition-
penalty signature, not a fundamental inability to read the script.

---

## Conclusions

1. The project's prior "fine-tuning works" conclusion was a metric artifact; treat Phases 3–4 as
   **not passed**.
2. With stable optimization, TrOCR **does** learn Bolorgir from 34 lines. CER 93.4% → 65.7% and
   real Armenian output is decisive directional proof.
3. Current blocker is purely training-recipe tuning (LR/schedule/epochs + generation settings), not
   a modeling dead end.

## Proposed next steps

1. **Re-overfit to convergence (the real Phase 3 gate).** Bump LR into the stable-but-faster band
   (~2–3e-5), use a cosine or constant schedule so it doesn't decay to 0 prematurely, train
   60–100 epochs. Target genuine overfit: **train-set CER < 0.10**. If it can't memorize 34 lines,
   stop and investigate further before scaling.
2. **Add anti-repetition at generation** (`no_repeat_ngram_size=3`, mild `repetition_penalty`) to
   kill the `աաաա` degeneracy; re-measure.
3. **Fix the source scripts.** `finetune_local.py` and `finetune_phase4.py` carry both bugs
   (LR 5e-5, `decoder_start_token_id=cls`). Update or mark deprecated so the broken recipe isn't
   reused. Add a fraction-vs-percent guard to all CER reporting.
4. **Correct the historical reports.** Add a correction banner to `phase_3_results.md` and
   `phase_2_vlm_results.md` (and the `finetune_phase4` numbers) noting the jiwer fraction/percent
   misread.
5. **Only then redo Phase 4 generalization** — train `page_0335`+`page_0543`, hold out `page_0559`,
   with the corrected stable recipe — to get the first *honest* held-out CER.

## Artifacts

- `ml_vision/scripts/finetune_fix.py` — decoder-start fix, lr=5e-5 (still unstable; superseded).
- `ml_vision/scripts/finetune_lowlr.py` — stabilized recipe used here.
- `ml_vision/scripts/inspect_phase4_eval.py` — checkpoint inspector (pred vs ref, char-set diag).
- `ml_vision/checkpoints/finetune_lowlr/checkpoint-195` — best checkpoint (65.7% train CER).
