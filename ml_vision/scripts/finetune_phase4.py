"""
Phase 4 — Generalization fine-tuning.

Train set : page_0335 (Phase 0 golden) + page_0543  (~119 non-empty lines)
Eval set  : page_0559 (held-out, never seen during training) (~89 non-empty lines)

Starts from microsoft/trocr-base-printed (not the Phase 3 overfit checkpoint)
so the generalization result is clean.
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
from grabar_generation import configure_generation

PHASE4_DIR = Path("data/phase4_dataset")
TRAIN_PAGES = ["page_0335", "page_0543"]
EVAL_PAGES = ["page_0559"]

MODEL_ID = "microsoft/trocr-base-printed"
OUTPUT_DIR = Path("ml_vision/checkpoints/finetune_phase4")


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

# decoder_start_token_id MUST be TrOCR's canonical </s>=eos (2), not cls=0:
# the cls override drove the degenerate blank/garbage collapse (see
# reports/phase_3_refinetune_results.md).
model.config.decoder_start_token_id = processor.tokenizer.eos_token_id
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
    num_train_epochs=20,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=2,
    per_device_eval_batch_size=4,
    learning_rate=2e-5,  # 5e-5 diverged (loss osc. 3<->11, grad norm 300-900)
    max_grad_norm=1.0,
    lr_scheduler_type="cosine",
    warmup_steps=30,
    predict_with_generate=True,
    generation_max_length=64,
    eval_strategy="epoch",
    save_strategy="epoch",
    save_total_limit=3,
    load_best_model_at_end=True,
    metric_for_best_model="cer",
    greater_is_better=False,
    logging_steps=10,
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

# jiwer CER is a FRACTION: 1.0 == 100% (degenerate), NOT 1%. The verdict thresholds
# below are already in fraction terms (eval_cer < 0.15) and remain correct.
results = trainer.evaluate()
eval_cer = results["eval_cer"]
print(f"\n=== Phase 4 held-out CER: {eval_cer:.4f} (fraction)  =  {eval_cer * 100:.1f}% ===")
print(f"Eval pages (never seen during training): {EVAL_PAGES}")

if eval_cer < 0.15:
    verdict = "PASS — generalization confirmed. Move to Phase 5 (server setup)."
elif eval_cer < 0.40:
    verdict = "PARTIAL — collect more data (~500-1000 lines) before server work."
else:
    verdict = "FAIL — model not generalizing. Investigate script style, augmentation, or base model."

print(f"Gate verdict: {verdict}")
