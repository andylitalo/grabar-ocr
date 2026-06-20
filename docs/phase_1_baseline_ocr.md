# Phase 1 — Baseline OCR (Off-the-Shelf TrOCR)

**Status:** Complete
**Prerequisite:** Phase 0 complete (line crops + `.txt` ground truth for 1 page)
**Runs on:** Mac M1 Pro (CPU or MPS) — no server or GPU required

---

## Goal
Measure the Character Error Rate (CER) of the off-the-shelf HuggingFace TrOCR model on the Phase 0 Bolorgir line crops — before any fine-tuning, before any server setup, with minimal code.

This phase answers the most important early question: **how far is the pre-trained model from useful?** The answer determines how much labeling and training effort is actually worth investing.

---

## Background: Why TrOCR?

TrOCR (Microsoft, 2021) is a transformer-based OCR model: a ViT image encoder + GPT-2-style text decoder, pre-trained on large printed and handwritten text corpora. It has no explicit knowledge of Armenian script, but its general visual-feature encoder may still produce meaningful partial matches. The `trocr-base-printed` variant is trained on printed text — the closest match to Bolorgir typeface.

The language-model decoder is the component that would need to "know" Armenian script and pativ abbreviation expansion patterns. That knowledge only comes from fine-tuning.

---

## Setup

Install dependencies (Mac, no GPU required):

```bash
cd ml_vision
pip install transformers Pillow jiwer torch
# On Apple Silicon, torch uses MPS by default — no extra flags needed
```

---

## Inference Script

Create a scratch script (e.g., `ml_vision/notebooks/baseline_eval.py`) — this is a one-off diagnostic, not production code:

```python
"""Baseline CER evaluation: off-the-shelf TrOCR on Phase 0 line crops."""

from pathlib import Path
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
from jiwer import cer
import torch

MODEL_ID = "microsoft/trocr-base-printed"
GOLDEN_DIR = Path("data/golden/page_0001")

processor = TrOCRProcessor.from_pretrained(MODEL_ID)
model = VisionEncoderDecoderModel.from_pretrained(MODEL_ID)
model.eval()

# Use MPS on Apple Silicon if available
device = "mps" if torch.backends.mps.is_available() else "cpu"
model = model.to(device)

predictions = []
references = []

for txt_path in sorted(GOLDEN_DIR.glob("*.txt")):
    ground_truth = txt_path.read_text(encoding="utf-8").strip()
    if not ground_truth:
        continue  # skip empty lines (headers, folios)

    img_path = txt_path.with_suffix(".png")
    image = Image.open(img_path).convert("RGB")
    pixel_values = processor(images=image, return_tensors="pt").pixel_values.to(device)

    with torch.no_grad():
        generated_ids = model.generate(pixel_values)
    prediction = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

    predictions.append(prediction)
    references.append(ground_truth)
    print(f"{img_path.name}: '{prediction}' | GT: '{ground_truth}'")

overall_cer = cer(references, predictions)
print(f"\n=== Baseline CER: {overall_cer:.4f} ({overall_cer * 100:.1f}%) ===")
print(f"Lines evaluated: {len(references)}")
```

Run from the repo root:
```bash
python ml_vision/notebooks/baseline_eval.py
```

---

## What to Look For

Go beyond the single CER number. Inspect the printed output line-by-line for patterns:

| Pattern | What it means |
|---------|---------------|
| Model outputs Latin/Latin-like chars | Encoder has no Armenian script concept; fine-tuning is essential |
| Model outputs garbled Unicode | Tokenizer may not cover Armenian code points well — check if `trocr-large` fares better |
| Model gets ~50% of characters right | Partial visual match; fine-tuning should improve significantly |
| Model outputs empty strings | Image preprocessing issue (contrast, size) — fix before continuing |
| Pativ abbreviations always wrong | Expected; the decoder has no expansion knowledge — fine-tuning target |
| Numerals / punctuation correct, letters wrong | Encoder works; only the Armenian-specific vocabulary is missing |

### Model variants to try (in order)
1. `microsoft/trocr-base-printed` — fastest, good starting point
2. `microsoft/trocr-large-printed` — larger decoder, may generalize better
3. `microsoft/trocr-base-handwritten` — Bolorgir is technically a printed script but has calligraphic features; worth one test

Record CER for each variant tried.

---

## Results Table

*(Fill in after running)*

| Model | CER | Notes |
|-------|-----|-------|
| `trocr-base-printed` | 93.4% | Best variant; Latin-like output; word-count structure preserved |
| `trocr-large-printed` | 97.9% | Worse; more `***` collapses; receipt-vocabulary hallucinations |
| `trocr-base-handwritten` | 138.7% | Worst; fluent English nonsense; CER > 100% due to long insertions |

---

## Gate Condition

**Phase 1 is complete when:** CER is recorded for at least one model variant and the failure modes are documented above.

Any CER value passes the gate — this is diagnostic, not pass/fail.

---

## Decision Tree After Gate

| Baseline CER | Recommended next step |
|---|---|
| < 5% | Re-examine: is the ground truth correct? Is the model accidentally right? If CER is genuinely low, fine-tuning may not be needed — skip Phase 3 and go straight to serving. |
| 5%–30% | Encouraging. Fine-tuning on even a small dataset (Phase 0 crops) is likely to drive this down further. Proceed to Phase 2 (server bootstrap) + Phase 3. |
| 30%–70% | Moderate baseline. Fine-tuning needed. Consider whether `trocr-large` is meaningfully better before committing to training. |
| > 70% | Model has essentially no Armenian script knowledge. Fine-tuning is essential and will likely yield dramatic improvement. Possibly consider a different base model (e.g., a multilingual OCR model with script coverage). |

---

## Notes / Findings

- Best model: `trocr-base-printed` (93.4% CER). Larger/handwritten variants perform worse on Bolorgir.
- No Armenian Unicode produced by any model — decoder vocabulary is Latin-only. Fine-tuning must teach an entirely new output character set.
- Visual encoder captures word-count structure (3-word lines → ~3 tokens), suggesting the ViT encoder is doing useful work; only the decoder needs retraining.
- `՚ի` elision glyph partially recognized across models (`'H`, `'B`) — latent sensitivity to some Bolorgir shapes.
- Section markers always hallucinated — model has no "no text" concept; a confidence threshold or post-processing step will be needed in the pipeline.
- `trocr-base-handwritten` CER > 100% due to long insertion hallucinations (generates more characters than exist in reference).
- Decision tree outcome: CER > 70% → fine-tuning essential; expected dramatic improvement even from small dataset.
- Full per-line output and failure mode analysis in `reports/phase_1_results.md`.
