# Phase 3 — TrOCR Fine-Tuning (M1 Pro Proof of Concept)

**Status:** Complete
**Prerequisite:** Phase 2 complete — proceed here only if all Phase 2 VLM/Transkribus results have CER ≥ 15%
**Runs on:** MacBook Pro M1 Pro, 32GB RAM — Apple MPS acceleration, no server required

---

## Goal

Fine-tune `trocr-base-printed` on the 34 labeled lines from Phase 0 using Apple MPS (Metal) acceleration. Prove that CER drops meaningfully from the 93.4% Phase 1 baseline before investing time in server infrastructure.

---

## Feasibility Check

| Concern | Assessment |
|---------|-----------|
| Model size in RAM | trocr-base-printed = ~334M params = ~1.3GB weights; Adam optimizer ~2.6GB extra; fits easily in 32GB |
| MPS support | PyTorch ≥ 2.0 supports MPS for transformer training; HuggingFace Seq2SeqTrainer works on MPS |
| Armenian tokenization | GPT-2 byte-level BPE tokenizer handles arbitrary Unicode — Armenian chars tokenize as multi-byte sequences; no vocabulary changes needed |
| Dataset size | 34 lines is tiny; high overfitting risk. We train/eval on the same 34 lines — this is a concept proof, not a generalizable model |
| Training time | ~34 lines × ~50 epochs ≈ minutes on MPS |

---

## Setup

```bash
cd /Users/andylitalo/church/grabar-ocr
source .venv/bin/activate
pip install accelerate sentencepiece
```

---

## Fine-Tuning Script

Script already written at `ml_vision/scripts/finetune_local.py`.

Run from repo root:
```bash
python ml_vision/scripts/finetune_local.py
```

Key parameters in the script:
- `MODEL_ID = "microsoft/trocr-base-printed"`
- `num_train_epochs = 50`
- `learning_rate = 5e-5`
- `per_device_train_batch_size = 4`
- Output: `ml_vision/checkpoints/finetune_poc/`

---

## What to Look For

- **CER drops below ~10%**: Strong overfit to training set (expected with 34 lines/50 epochs). Proves the model *can* learn Armenian. Generalization tested in a later phase with more data.
- **CER 10%–50%**: Partial learning — try more epochs or lower LR.
- **CER stays near 93%**: Training isn't converging — likely a config issue (decoder start token, learning rate). Debug before assuming the approach is wrong.
- **MPS errors / crashes**: Fall back to `use_mps_device=False` for CPU training; slower but functionally identical.

---

## Results

*(Fill in after running)*

| Run | Epochs | LR | Train CER | Notes |
|-----|--------|----|-----------|-------|
| 1 (aborted at epoch 28) | 28 | 5e-5 | ~100% | `generation_max_length` not set — default 21 tokens truncated all Armenian output; CER metric was broken |
| 2 (best checkpoint: epoch 16) | 23/50 (stopped early) | 5e-5 | **1.0%** | Fixed `generation_max_length=64`; gate met at epoch 7 (3.03%); best at epoch 16 (1.0%); stopped at epoch 23 once loss plateaued |

---

## Gate Condition

**Phase 3 is complete when:** Fine-tuned CER is measurably lower than the 93.4% Phase 1 baseline on the training set, confirming the model can learn Armenian script from this data.

---

## Decision After Gate

| Fine-tuned train CER | Next step |
|---|---|
| < 20% | Concept proven. Collect more labeled data; move to server for full fine-tuning run. |
| 20%–60% | Partial learning. Try more epochs or lower LR. If plateau reached, expand dataset before moving to server. |
| > 60% | Not converging. Check decoder config; revisit Phase 2 VLM alternatives. |

---

## Notes / Findings

- **Gate met at epoch 7** (3.03% CER on 34-line training set). Concept proven: the model can learn Armenian script from this data.
- **Best checkpoint: epoch 16** (1.0% CER, loss 4.401). Saved to `ml_vision/checkpoints/finetune_poc/`.
- **CER oscillation is expected** with 34 samples — loss trended steadily downward (10.05 → 3.07) while CER bounced between 1–14%. `load_best_model_at_end=True` captured the 1.0% epoch regardless.
- **Script fix required:** `use_mps_device` arg removed in transformers 5.x (MPS auto-detected now). Also, `generation_max_length=64` must be set explicitly — the default of 21 tokens truncates Armenian output and makes CER meaningless.
- **compute_metrics fix required:** With `predict_with_generate=True`, `eval_pred.predictions` are token IDs, not logits. MPS also pads generated sequences with large sentinel values that overflow the Rust tokenizer's u32 range — must clip to `[0, vocab_size-1]` before decoding.
- **No value in running all 50 epochs** once the gate is met and loss has plateaued — this is intentional overfit on 34 lines. Stopped at epoch 23.
- **Decision tree outcome:** CER < 20% (actually 1.0%) → concept proven. Next step: collect more labeled data to test generalization before moving to server.
