"""
Phase 3 convergence run — the decisive overfit experiment.

The stabilized low-LR run (finetune_lowlr.py) proved the model CAN learn Bolorgir
(93.4% -> 65.7% train CER, real Armenian output) but was cut off undertrained: the
LINEAR LR schedule decayed to ~0 while loss was still falling at epoch 40, and
generation showed token-repetition degeneracy (`աաաա`).

This run pushes to genuine convergence to settle the real Phase 3 gate
(train-set CER < 0.10 — can the model memorize 34 lines?). RESULT: GATE PASSES —
0.064 CER greedy / 0.026 beam-4 on the 34 lines (see reports/phase_3_converge_results.md).

Changes vs finetune_lowlr.py:
  - learning_rate 1e-5 -> 2e-5  (between the stable 1e-5 and the unstable 5e-5)
  - lr_scheduler_type "linear" -> "cosine" (decays slowly, won't hit ~0 mid-improvement)
  - num_train_epochs 40 -> 80

Kept: gradient_accumulation_steps=2, max_grad_norm=1.0, warmup_steps=30,
per_device_train_batch_size=4, decoder_start_token_id=eos(2).

Decoding is PENALTY-FREE. We initially added repetition penalties to suppress the
low-LR run's `աաաա` degeneracy, but that degeneracy was an undertraining artifact:
on the converged model the penalties inflate CER (0.064 -> 0.45) by punishing the
legitimate letter/n-gram reuse of real Grabar text. See grabar_generation.py.

Run: .venv/bin/python ml_vision/scripts/finetune_converge.py
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

import sys
sys.path.insert(0, str(Path(__file__).parent))
from grabar_generation import configure_generation, NUM_BEAMS

GOLDEN_DIR = Path("data/phase4_dataset/page_0335")
MODEL_ID = "microsoft/trocr-base-printed"
OUTPUT_DIR = Path("ml_vision/checkpoints/finetune_converge")


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

model.config.decoder_start_token_id = processor.tokenizer.eos_token_id  # 2 (TrOCR canonical)
model.config.pad_token_id = processor.tokenizer.pad_token_id
model.config.eos_token_id = processor.tokenizer.eos_token_id
model.config.vocab_size = model.config.decoder.vocab_size
model.generation_config.decoder_start_token_id = processor.tokenizer.eos_token_id
model.generation_config.pad_token_id = processor.tokenizer.pad_token_id
model.generation_config.eos_token_id = processor.tokenizer.eos_token_id
model.generation_config.max_length = 64
# Penalty-free decoding: repetition penalties HURT the converged model (see
# grabar_generation.py / reports/phase_3_converge_results.md). The `աաաա` degeneracy
# was an undertraining artifact, fixed by convergence — not by generation penalties.
configure_generation(model)

dataset = GrabarLineDataset(GOLDEN_DIR, processor)
print(
    f"Dataset size: {len(dataset)} lines | LR=2e-5 | cosine | grad_accum=2 | "
    f"max_grad_norm=1.0 | 80 epochs | penalty-free decoding"
)

training_args = Seq2SeqTrainingArguments(
    output_dir=str(OUTPUT_DIR),
    num_train_epochs=80,
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
    train_dataset=dataset,
    eval_dataset=dataset,
    data_collator=default_data_collator,
    compute_metrics=lambda p: compute_metrics(p, processor),
)

trainer.train()

results = trainer.evaluate()
c = results["eval_cer"]
print(f"\n=== Fine-tuned train-set CER: {c:.4f}  (fraction)  =  {c*100:.1f}%  ===")
print("(jiwer CER is a fraction: 1.0 == 100%. The Phase 3 gate is train-set CER < 0.10.)")
print(f"Gate (< 0.10): {'PASS' if c < 0.10 else 'NOT YET'}")

device = model.device
model.eval()
print(f"\nSample predictions (beam search, num_beams={NUM_BEAMS}):")
for img_path, ref in dataset.samples[:8]:
    image = Image.open(img_path).convert("RGB")
    pv = processor(images=image, return_tensors="pt").pixel_values.to(device)
    with torch.no_grad():
        gen = model.generate(pv, max_length=64, num_beams=NUM_BEAMS)
    pred = processor.batch_decode(gen, skip_special_tokens=True)[0]
    print(f"  CER {cer(ref, pred):.3f} | PRED {pred!r}")
    print(f"            | REF  {ref!r}")
