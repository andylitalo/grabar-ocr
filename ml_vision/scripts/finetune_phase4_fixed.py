"""
Phase 4 (FIXED) — first *honest* generalization fine-tuning.

Supersedes the original finetune_phase4.py run, whose "held-out" numbers were the
same degenerate collapse + jiwer fraction/percent misread that invalidated Phase 3
(see reports/phase_3_refinetune_results.md). This script uses the corrected stable
recipe and reports CER as both fraction and percent with sample predictions.

Train set : page_0335 (Phase 0 golden) + page_0543
Eval set  : page_0559 (held-out, never seen during training)
Base      : microsoft/trocr-base-printed (clean generalization measurement)

Recipe (matches finetune_converge.py): decoder_start=eos(2), lr=2e-5, cosine,
grad_accum=2, max_grad_norm=1.0, warmup 30, PENALTY-FREE decoding (repetition
penalties hurt the converged model — see grabar_generation.py lesson).

Run: .venv/bin/python ml_vision/scripts/finetune_phase4_fixed.py
"""

from pathlib import Path
from functools import partial

import numpy as np
import torch
from PIL import Image
from jiwer import cer
from torch.utils.data import Dataset
from transformers import (
    TrOCRProcessor,
    VisionEncoderDecoderModel,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    default_data_collator,
)

import sys
sys.path.insert(0, str(Path(__file__).parent))
from grabar_generation import configure_generation, NUM_BEAMS

PHASE4_DIR = Path("data/phase4_dataset")
TRAIN_PAGES = ["page_0335", "page_0543"]
EVAL_PAGES = ["page_0559"]

MODEL_ID = "microsoft/trocr-base-printed"
OUTPUT_DIR = Path("ml_vision/checkpoints/finetune_phase4_fixed")


class GrabarLineDataset(Dataset):
    def __init__(self, page_dirs: list[Path], processor: TrOCRProcessor):
        self.samples: list[tuple[Path, str]] = []
        for page_dir in page_dirs:
            for txt_path in sorted(page_dir.glob("*.txt")):
                text = txt_path.read_text(encoding="utf-8").strip()
                if text:  # skip empty (section markers, folios)
                    self.samples.append((txt_path.with_suffix(".png"), text))
        self.processor = processor

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict:
        img_path, text = self.samples[idx]
        image = Image.open(img_path).convert("RGB")
        pixel_values = self.processor(images=image, return_tensors="pt").pixel_values.squeeze()
        labels = self.processor.tokenizer(
            text, padding="max_length", max_length=64, truncation=True, return_tensors="pt"
        ).input_ids.squeeze()
        labels[labels == self.processor.tokenizer.pad_token_id] = -100
        return {"pixel_values": pixel_values, "labels": labels}


def compute_metrics(eval_pred, processor: TrOCRProcessor) -> dict:
    pred_ids, label_ids = eval_pred
    vocab_size = processor.tokenizer.vocab_size
    pred_ids = np.clip(np.asarray(pred_ids, dtype=np.int64), 0, vocab_size - 1)
    label_ids = np.asarray(label_ids, dtype=np.int64)
    label_ids[label_ids == -100] = processor.tokenizer.pad_token_id
    predictions = processor.batch_decode(pred_ids.tolist(), skip_special_tokens=True)
    references = processor.batch_decode(label_ids.tolist(), skip_special_tokens=True)
    return {"cer": cer(references, predictions)}


processor = TrOCRProcessor.from_pretrained(MODEL_ID)
model = VisionEncoderDecoderModel.from_pretrained(MODEL_ID)

model.config.decoder_start_token_id = processor.tokenizer.eos_token_id  # 2 (TrOCR canonical)
model.config.pad_token_id = processor.tokenizer.pad_token_id
model.config.eos_token_id = processor.tokenizer.eos_token_id
model.config.vocab_size = model.config.decoder.vocab_size
model.generation_config.decoder_start_token_id = processor.tokenizer.eos_token_id
model.generation_config.pad_token_id = processor.tokenizer.pad_token_id
model.generation_config.eos_token_id = processor.tokenizer.eos_token_id
model.generation_config.max_length = 64
configure_generation(model)  # penalty-free decoding (see grabar_generation.py lesson)

train_dirs = [PHASE4_DIR / p for p in TRAIN_PAGES]
eval_dirs = [PHASE4_DIR / p for p in EVAL_PAGES]

train_dataset = GrabarLineDataset(train_dirs, processor)
eval_dataset = GrabarLineDataset(eval_dirs, processor)

print(f"Train lines : {len(train_dataset)} (pages: {TRAIN_PAGES})")
print(f"Eval lines  : {len(eval_dataset)} (pages: {EVAL_PAGES})")

training_args = Seq2SeqTrainingArguments(
    output_dir=str(OUTPUT_DIR),
    num_train_epochs=40,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=2,
    per_device_eval_batch_size=4,
    learning_rate=2e-5,
    max_grad_norm=1.0,
    lr_scheduler_type="cosine",
    warmup_steps=30,
    predict_with_generate=True,
    generation_max_length=64,
    eval_strategy="epoch",
    save_strategy="epoch",
    save_total_limit=2,
    load_best_model_at_end=True,
    metric_for_best_model="cer",
    greater_is_better=False,
    logging_strategy="epoch",
    report_to="none",
)

trainer = Seq2SeqTrainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    data_collator=default_data_collator,
    compute_metrics=partial(compute_metrics, processor=processor),
)

trainer.train()

# jiwer CER is a FRACTION: 1.0 == 100% (degenerate), NOT 1%.
results = trainer.evaluate()
eval_cer = results["eval_cer"]
print(f"\n=== Phase 4 held-out CER: {eval_cer:.4f} (fraction)  =  {eval_cer*100:.1f}% ===")
print(f"Eval pages (never seen during training): {EVAL_PAGES}")

if eval_cer < 0.15:
    verdict = "PASS — generalization confirmed. Move to Phase 5 (server setup)."
elif eval_cer < 0.40:
    verdict = "PARTIAL — collect more data (~500-1000 lines) before server work."
else:
    verdict = "FAIL — model not generalizing. Investigate script style, augmentation, or base model."
print(f"Gate verdict: {verdict}")

# Sample predictions on the held-out page (honest, with anti-repetition generation).
device = model.device
model.eval()
print(f"\nHeld-out sample predictions (page_0559, beam search num_beams={NUM_BEAMS}):")
for img_path, ref in eval_dataset.samples[:10]:
    image = Image.open(img_path).convert("RGB")
    pv = processor(images=image, return_tensors="pt").pixel_values.to(device)
    with torch.no_grad():
        gen = model.generate(pv, max_length=64, num_beams=NUM_BEAMS)
    pred = processor.batch_decode(gen, skip_special_tokens=True)[0]
    print(f"  CER {cer(ref, pred):.3f} | PRED {pred!r}")
    print(f"            | REF  {ref!r}")
