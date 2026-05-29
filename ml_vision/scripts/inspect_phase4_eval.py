"""
Diagnostic: load the Phase 4 best checkpoint and dump prediction vs. ground truth
on the held-out page (page_0559), to tell apart a real generalization failure
from an eval/generation bug.

Run: .venv/bin/python ml_vision/scripts/inspect_phase4_eval.py
"""

from pathlib import Path

import torch
from PIL import Image
from jiwer import cer
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

import sys

BASE_ID = "microsoft/trocr-base-printed"
# Usage: inspect_phase4_eval.py [page_name] [checkpoint_path]
PAGE_NAME = sys.argv[1] if len(sys.argv) > 1 else "page_0559"
CKPT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("ml_vision/checkpoints/finetune_phase4/checkpoint-180")
EVAL_PAGE = Path("data/phase4_dataset") / PAGE_NAME
print(f"Checkpoint: {CKPT}")

device = "mps" if torch.backends.mps.is_available() else "cpu"

processor = TrOCRProcessor.from_pretrained(BASE_ID)
model = VisionEncoderDecoderModel.from_pretrained(CKPT).to(device)
model.eval()

samples: list[tuple[Path, str]] = []
for txt_path in sorted(EVAL_PAGE.glob("*.txt")):
    text = txt_path.read_text(encoding="utf-8").strip()
    if text:
        samples.append((txt_path.with_suffix(".png"), text))

print(f"Held-out page: {EVAL_PAGE.name}  |  non-empty lines: {len(samples)}  |  device: {device}\n")

preds: list[str] = []
refs: list[str] = []
for img_path, ref in samples:
    image = Image.open(img_path).convert("RGB")
    pixel_values = processor(images=image, return_tensors="pt").pixel_values.to(device)
    with torch.no_grad():
        generated_ids = model.generate(pixel_values, max_length=64)
    pred = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    preds.append(pred)
    refs.append(ref)

overall = cer(refs, preds)

# Print first 15 lines for eyeballing
print(f"{'line':<10} {'CER':>7}  PRED  |  REF")
print("-" * 90)
for (img_path, ref), pred in list(zip(samples, preds))[:15]:
    line_cer = cer(ref, pred)
    print(f"{img_path.stem:<10} {line_cer:>7.2f}  {pred!r}  |  {ref!r}")

print("-" * 90)
print(f"\nOverall held-out CER: {overall:.4f}  ({overall*100:.1f}%)")

# Quick character-set diagnostic: are predictions even Armenian?
def armenian_frac(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    arm = [c for c in letters if "԰" <= c <= "֏"]
    return len(arm) / len(letters)

pred_arm = sum(armenian_frac(p) for p in preds) / max(len(preds), 1)
empty = sum(1 for p in preds if not p.strip())
print(f"Mean Armenian-letter fraction in predictions: {pred_arm:.2f}")
print(f"Empty predictions: {empty}/{len(preds)}")
distinct = len(set(preds))
print(f"Distinct predictions: {distinct}/{len(preds)} (low => collapse to fixed output)")
