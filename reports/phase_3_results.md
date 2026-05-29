> ⚠️ **CORRECTION (2026-05-29) — these numbers are wrong; do not trust them.**
> Every CER figure below is jiwer's raw **fraction** mislabeled with `%`. jiwer returns
> `1.0` for **100%** CER, so the headline **"1.0% CER"** was actually **100% CER** — a
> degenerate model that emits only blank/space tokens (confirmed by teacher-forced forward
> pass). **Fine-tuning never actually worked here.** Root cause was optimizer divergence at
> `lr=5e-5`, not generalization. See **`reports/phase_3_refinetune_results.md`** for the full
> re-investigation and the stabilized recipe. Treat Phase 3 as **NOT passed** by this report.

# Phase 3 Results — TrOCR Fine-Tuning (M1 Pro Proof of Concept)

**Date completed:** 2026-04-25
**Baseline (trocr-base-printed, no fine-tuning):** 93.4% CER

---

## Summary

| Metric | Value |
|--------|-------|
| Best CER (train set, 34 lines) | **1.0%** (epoch 16) |
| Gate condition (< 20%) met at | epoch 7 (3.03% CER) |
| Epochs run | 23 of 50 (stopped early — loss plateaued) |
| Base model | `microsoft/trocr-base-printed` |
| Checkpoint saved | `ml_vision/checkpoints/finetune_poc/` |

---

## CER Per Epoch (Run 2 — corrected `generation_max_length=64`)

| Epoch | CER | Loss | Notes |
|-------|-----|------|-------|
| 1 | 181.8% | 10.05 | Random initialization — long generation = many insertions |
| 2 | 9.15% | 9.885 | Sharp drop — model starts learning Armenian |
| 3 | 13.77% | 9.957 | |
| 4 | 14.05% | 9.522 | |
| 5 | 9.15% | 9.388 | |
| 6 | 14.48% | 7.417 | |
| **7** | **3.03%** | 8.548 | **Gate condition met** |
| 8 | 3.05% | 6.726 | |
| 9 | 3.23% | 6.588 | |
| 10 | 11.99% | 8.56 | |
| 11 | 3.05% | 8.358 | |
| 12 | 9.15% | 7.937 | |
| 13 | 3.05% | 6.06 | |
| 14 | 3.05% | 5.389 | |
| 15 | 3.05% | 5.203 | |
| **16** | **1.0%** | 4.401 | **Best checkpoint** |
| 17 | 3.05% | 3.956 | |
| 18 | 3.05% | 3.691 | |
| 19 | 3.05% | 3.348 | |
| 20 | 3.05% | 3.206 | |
| 21 | 3.05% | 3.116 | |
| 22 | 3.05% | 3.084 | |
| 23 | 3.05% | 3.072 | Loss plateau — stopped here |

---

## Script Fixes Applied

Two bugs in `ml_vision/scripts/finetune_local.py` required fixing before training succeeded:

1. **`use_mps_device` removed** — deprecated and removed in transformers 5.x; MPS is now auto-detected.
2. **`generation_max_length=64` added** — default of 21 tokens truncates Armenian output (multi-byte BPE encoding means a ~25-char Armenian line needs ~40–80 tokens). Without this fix, CER was stuck at ~100% regardless of training.
3. **`compute_metrics` rewritten** — with `predict_with_generate=True`, `eval_pred.predictions` are already token IDs (not logits). MPS pads generated sequences with large sentinel values that overflow the Rust tokenizer's u32 range; must `np.clip` to `[0, vocab_size-1]` before decoding.

---

## Key Conclusions

1. **Concept proven.** Fine-tuning drops CER from 93.4% → 1.0% on the training set. The model can learn Armenian Bolorgir script from as few as 34 lines.
2. **Oscillation is inherent to 34-sample training.** CER bounced between 1–15% across epochs while loss trended steadily downward. `load_best_model_at_end=True` captures the best checkpoint regardless.
3. **No value in running all 50 epochs** once gate is met and loss plateaus — this is intentional overfit, not generalization training.
4. **CER on unseen data is unknown.** The 1.0% figure is train-set CER. Generalization requires more labeled pages.

---

## Decision Tree Outcome

Fine-tuned train CER = 1.0% → **< 20% threshold met** → Collect more labeled data; test generalization before moving to server.

## Next Step

**Phase 4:** Collect more labeled pages (~5–10 pages, ~150–300 lines) and measure held-out CER to determine whether the model generalizes before investing in server infrastructure.
