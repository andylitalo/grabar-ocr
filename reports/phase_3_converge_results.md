# Phase 3 Convergence — Gate PASSED + the repetition-penalty lesson

**Date:** 2026-05-29
**Script:** `ml_vision/scripts/finetune_converge.py`
**Base:** `microsoft/trocr-base-printed` (93.4% baseline CER)
**Builds on:** `reports/phase_3_refinetune_results.md` (stabilized low-LR run, 65.7% train CER)

---

## TL;DR

1. **The real Phase 3 gate (train-set CER < 0.10) PASSES.** The converged model
   memorizes the 34 golden lines: **0.064 CER greedy, 0.026 CER beam-4** — decisive
   proof TrOCR can learn Bolorgir.
2. **The decisive lesson: repetition penalties HURT a properly-trained model.** They
   were inflating the measured CER from 0.064 to 0.45. We have removed them; default
   decoding is now penalty-free.
3. Optimizer is fully converged (eval_loss 15.0 → 0.099, LR decayed to ~0, grad norm
   ~8). This is no longer an undertraining or instability problem.

---

## Training recipe

Stabilized recipe from `finetune_lowlr.py`, pushed to convergence:

| Knob | Value |
|------|-------|
| learning_rate | 2e-5 |
| lr_scheduler | cosine, warmup 30 |
| num_train_epochs | 80 |
| per_device_train_batch_size | 4 |
| gradient_accumulation_steps | 2 (effective batch 8) |
| max_grad_norm | 1.0 |
| decoder_start_token_id | eos = 2 (TrOCR canonical) |
| train = eval | `data/phase4_dataset/page_0335_auto` (34 lines) |

Training was clean and monotonic — eval_loss 15.0 (ep1) → 0.099 (ep80), grad norms
stayed ~8–80 (vs the 300–900 divergence of the original `lr=5e-5` recipe).

---

## The repetition-penalty trap

During training we initially set anti-repetition generation options to suppress the
low-LR run's `աաաա` / `եեեե` degeneracy. They were applied to the per-epoch eval, so
the trainer reported a **best eval CER of 0.4544** — and the run looked like it had
*failed* the gate.

Decoding the *same converged checkpoint* (`checkpoint-325`, epoch 65) four ways
revealed the penalties were the problem, not the model:

| Decoding config | Train-set CER |
|-----------------|:-------------:|
| repetition_penalty=1.3 + no_repeat_ngram=3 + soft bigram (1.3) | 0.4544 |
| repetition_penalty=1.3 + no_repeat_ngram=3 | 0.3219 |
| **plain greedy (no penalties)** | **0.0641** |
| **beam search, num_beams=4 (no penalties)** | **0.0256** |

### Why they hurt

- **`repetition_penalty=1.3`** discourages re-emitting *any* token already used
  anywhere earlier in the line. Real Grabar lines reuse letters constantly, so this
  broadly biases the model off its own (correct, memorized) output.
- **`no_repeat_ngram_size=3`** hard-bans (`-inf`) any 3-token run from recurring —
  forbidding legitimately recurring trigrams outright.
- **Soft bigram penalty** (added on the hypothesis that doubled letters are rare in
  Grabar) compounded the above: 0.32 → 0.45.

The `աաաա` degeneracy was an **undertraining artifact**, cured by convergence — not a
generation problem to be patched with penalties. Worse, applying the penalties at
eval time was itself **distorting the metric** — the very failure mode this whole
debugging effort exists to eliminate.

### Resolution

Default decoding is now **penalty-free** (`grabar_generation.configure_generation`
sets `repetition_penalty=1.0`, `no_repeat_ngram_size=0`). Beam search
(`num_beams=4`) is the recommended inference setting. `SoftNoRepeatNGramLogitsProcessor`
is retained only as a documented, opt-in escape hatch for genuine degeneracy on
unseen data.

---

## Sample predictions (beam-4, penalty-free) on `page_0335_auto`

The model reproduces the training lines almost exactly; residual errors are isolated
character substitutions, not structural failure or repetition.

---

## Conclusions

1. **Phase 3 gate PASSED** — TrOCR genuinely overfits 34 Bolorgir lines (0.064 greedy
   / 0.026 beam). The modeling approach is sound.
2. Repetition penalties are off by default; convergence, not generation tricks, is the
   fix for degeneracy.
3. **Next:** Phase 4 honest generalization — train `page_0335_auto`+`page_0543_human`, hold out
   `page_0559_human`, penalty-free recipe → `reports/phase_4_results.md`.

## Artifacts

- `ml_vision/scripts/finetune_converge.py` — convergence run (this report).
- `ml_vision/scripts/grabar_generation.py` — `configure_generation` (penalty-free) +
  opt-in `SoftNoRepeatNGramLogitsProcessor`.
- `ml_vision/checkpoints/finetune_converge/checkpoint-325` — best checkpoint (0.064/0.026).
- `reports/logs/finetune_converge.log` — full training log.
