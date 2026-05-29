"""
Phase 3 RE-RUN with the decoder-start-token fix.

Context: the original finetune_local.py / finetune_phase4.py set
    model.config.decoder_start_token_id = processor.tokenizer.cls_token_id  # = 0
which overrides TrOCR's canonical decoder start token (</s> = 2). With the wrong
start token the decoder collapsed to emitting the space token (1437) for every
position — confirmed via teacher-forced forward pass (loss ~4.6, argmax all spaces).
The "1.0% CER" in reports/phase_3_results.md was a misread of jiwer's raw fraction
1.0 (= 100% CER); fine-tuning never actually worked.

This script trains on the single golden page (page_0335, 34 lines) with the correct
start token, and reports CER honestly (fraction AND percent) plus sample predictions.

Run: .venv/bin/python ml_vision/scripts/finetune_fix.py
"""

from pathlib import Path

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

GOLDEN_DIR = Path("data/phase4_dataset/page_0335")
MODEL_ID = "microsoft/trocr-base-printed"
OUTPUT_DIR = Path("ml_vision/checkpoints/finetune_fix")


class GrabarLineDataset(Dataset):
    def __init__(self, page_dir: Path, processor: TrOCRProcessor):
        self.samples: list[tuple[Path, str]] = []
        for txt_path in sorted(page_dir.glob("*.txt")):
            text = txt_path.read_text(encoding="utf-8").strip()
            if text:
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

# --- THE FIX: use TrOCR's canonical decoder start token (</s> = 2), not cls (0) ---
model.config.decoder_start_token_id = processor.tokenizer.eos_token_id  # 2
model.config.pad_token_id = processor.tokenizer.pad_token_id
model.config.eos_token_id = processor.tokenizer.eos_token_id
model.config.vocab_size = model.config.decoder.vocab_size
# keep generation config in sync so saved checkpoint generates correctly
model.generation_config.decoder_start_token_id = processor.tokenizer.eos_token_id
model.generation_config.pad_token_id = processor.tokenizer.pad_token_id
model.generation_config.eos_token_id = processor.tokenizer.eos_token_id
model.generation_config.max_length = 64

print(f"decoder_start_token_id = {model.config.decoder_start_token_id} (was 0/cls before fix)")

dataset = GrabarLineDataset(GOLDEN_DIR, processor)
print(f"Dataset size: {len(dataset)} lines")

training_args = Seq2SeqTrainingArguments(
    output_dir=str(OUTPUT_DIR),
    num_train_epochs=40,
    per_device_train_batch_size=4,
    per_device_eval_batch_size=4,
    learning_rate=5e-5,
    warmup_steps=10,
    predict_with_generate=True,
    generation_max_length=64,
    eval_strategy="epoch",
    save_strategy="epoch",
    save_total_limit=2,
    load_best_model_at_end=True,
    metric_for_best_model="cer",
    greater_is_better=False,
    logging_steps=10,
    report_to="none",
)

trainer = Seq2SeqTrainer(
    model=model,
    args=training_args,
    train_dataset=dataset,
    eval_dataset=dataset,  # same set — overfit proof-of-concept
    data_collator=default_data_collator,
    compute_metrics=lambda p: compute_metrics(p, processor),
)

trainer.train()

results = trainer.evaluate()
c = results["eval_cer"]
print(f"\n=== Fine-tuned train-set CER: {c:.4f}  (fraction)  =  {c*100:.1f}%  ===")
print("(jiwer CER is a fraction: 1.0 == 100%. A working overfit should be well under 0.10.)")

# Show real sample predictions so the result is unambiguous
device = model.device
model.eval()
print("\nSample predictions:")
for img_path, ref in dataset.samples[:8]:
    image = Image.open(img_path).convert("RGB")
    pv = processor(images=image, return_tensors="pt").pixel_values.to(device)
    with torch.no_grad():
        gen = model.generate(pv, max_length=64)
    pred = processor.batch_decode(gen, skip_special_tokens=True)[0]
    print(f"  CER {cer(ref, pred):.3f} | PRED {pred!r}")
    print(f"            | REF  {ref!r}")
