"""
Local M1 fine-tuning proof-of-concept.
Trains trocr-base-printed on Phase 0 golden data using Apple MPS.
"""

from pathlib import Path
from PIL import Image
from transformers import (
    TrOCRProcessor,
    VisionEncoderDecoderModel,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    default_data_collator,
)
from torch.utils.data import Dataset
from jiwer import cer
import numpy as np
import torch

import sys
sys.path.insert(0, str(Path(__file__).parent))
from grabar_generation import configure_generation

GOLDEN_DIR = Path("data/golden/page_0001")
MODEL_ID = "microsoft/trocr-base-printed"
OUTPUT_DIR = Path("ml_vision/checkpoints/finetune_poc")


class GrabarLineDataset(Dataset):
    def __init__(self, golden_dir: Path, processor: TrOCRProcessor):
        self.samples = []
        for txt_path in sorted(golden_dir.glob("*.txt")):
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
        # Replace padding token id with -100 so loss ignores padding
        labels[labels == self.processor.tokenizer.pad_token_id] = -100
        return {"pixel_values": pixel_values, "labels": labels}


def compute_metrics(eval_pred, processor: TrOCRProcessor):
    # With predict_with_generate=True, predictions are already token IDs, not logits.
    # MPS pads generated sequences with large sentinel values that overflow the Rust
    # tokenizer's u32 range — clip to valid vocab range before decoding.
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

# Required config for Seq2Seq generation.
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

dataset = GrabarLineDataset(GOLDEN_DIR, processor)
print(f"Dataset size: {len(dataset)} lines")

training_args = Seq2SeqTrainingArguments(
    output_dir=str(OUTPUT_DIR),
    num_train_epochs=50,
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
    eval_dataset=dataset,  # same set — concept proof only
    data_collator=default_data_collator,
    compute_metrics=lambda p: compute_metrics(p, processor),
)

trainer.train()

# Final eval. jiwer CER is a FRACTION: 1.0 == 100% (a degenerate model), NOT 1%.
results = trainer.evaluate()
c = results["eval_cer"]
print(f"\n=== Fine-tuned CER: {c:.4f} (fraction)  =  {c*100:.1f}% ===")
print("(jiwer CER is a fraction: 1.0 == 100%. A working overfit should be well under 0.10.)")
print(f"Baseline was: 0.934 (93.4%)")
print(f"Improvement: {(0.934 - c)*100:.1f} percentage points")
