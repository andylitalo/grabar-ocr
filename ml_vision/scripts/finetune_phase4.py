"""
Phase 4 — CER-vs-training-size scaling experiment.

Trains microsoft/trocr-base-printed on a nested train split (50 ⊂ 150 ⊂ 500
lines) and ALWAYS evaluates against the same frozen 100-line test set, so CER
across runs is directly comparable.

Usage:
    python ml_vision/scripts/finetune_phase4.py --splits data/phase4_scaling/splits_50.json
    python ml_vision/scripts/finetune_phase4.py --splits data/phase4_scaling/splits_500.json --wandb

The split file (built by data_prep/build_scaling_splits.py) supplies the train
ids, the frozen test dir, the seed, and n_train. Starts from the base printed
model (not a Phase 3 checkpoint) so each generalization result is clean.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from functools import partial
from pathlib import Path

import numpy as np
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

sys.path.insert(0, str(Path(__file__).parent))
from grabar_generation import configure_generation

REPO = Path(__file__).resolve().parent.parent.parent
PHASE4_DIR = REPO / "data/phase4_dataset"
MODEL_ID = "microsoft/trocr-base-printed"


def samples_from_dirs(dirs: list[Path]) -> list[tuple[Path, str]]:
    """Collect (png, text) pairs from flat line dirs, skipping empty .txt files.

    Used for the frozen test set (flat line_NNN.{png,txt}).
    """
    samples: list[tuple[Path, str]] = []
    for d in dirs:
        for txt_path in sorted(d.glob("*.txt")):
            text = txt_path.read_text(encoding="utf-8").strip()
            if text:  # skip empty (section markers, folios)
                png = txt_path.with_suffix(".png")
                if png.exists():
                    samples.append((png, text))
    return samples


def samples_from_splits(splits_path: Path, phase4_dir: Path) -> list[tuple[Path, str]]:
    """Resolve a split file's train ids ('page_XXXX/line_NNN') to (png, text)."""
    split = json.loads(splits_path.read_text(encoding="utf-8"))
    samples: list[tuple[Path, str]] = []
    for line_id in split["train"]:
        txt_path = phase4_dir / f"{line_id}.txt"
        text = txt_path.read_text(encoding="utf-8").strip()
        if text:
            png = txt_path.with_suffix(".png")
            if png.exists():
                samples.append((png, text))
    return samples


class GrabarLineDataset(Dataset):
    def __init__(self, samples: list[tuple[Path, str]], processor: TrOCRProcessor):
        self.samples = samples
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--splits", type=Path, required=True, help="path to splits_{N}.json (defines train set)"
    )
    parser.add_argument(
        "--wandb", action="store_true", help="log to W&B online (default: offline)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume from the latest checkpoint in OUTPUT_DIR (if a run was interrupted)",
    )
    args = parser.parse_args()

    # W&B convention (CLAUDE.md): always report_to wandb, but default to offline so
    # runs don't block on login. --wandb (or WANDB_MODE=online) opts into online.
    if args.wandb:
        os.environ["WANDB_MODE"] = "online"
    else:
        os.environ.setdefault("WANDB_MODE", "offline")

    splits_path = args.splits if args.splits.is_absolute() else REPO / args.splits
    split = json.loads(splits_path.read_text(encoding="utf-8"))
    n_train = split["n_train"]
    seed = split["seed"]
    frozen_dir = REPO / split["frozen_test_dir"]

    output_dir = REPO / f"ml_vision/checkpoints/finetune_phase4_scale_{n_train}"

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

    train_samples = samples_from_splits(splits_path, PHASE4_DIR)
    eval_samples = samples_from_dirs([frozen_dir])  # constant 100-line set for all runs
    train_dataset = GrabarLineDataset(train_samples, processor)
    eval_dataset = GrabarLineDataset(eval_samples, processor)

    print(f"Train lines : {len(train_dataset)} (from {splits_path.relative_to(REPO)})")
    print(f"Eval lines  : {len(eval_dataset)} (frozen: {frozen_dir.relative_to(REPO)})")

    training_args = Seq2SeqTrainingArguments(
        output_dir=str(output_dir),
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
        report_to="wandb",
        run_name=f"phase4-scale-{n_train}",
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=default_data_collator,
        compute_metrics=partial(compute_metrics, processor=processor),
    )

    trainer.train(resume_from_checkpoint=args.resume or None)

    # jiwer CER is a FRACTION: 1.0 == 100% (degenerate), NOT 1%.
    results = trainer.evaluate()
    eval_cer = results["eval_cer"]
    n_test = len(eval_dataset)
    print(f"\n=== Phase 4 scale n_train={n_train}: held-out CER "
          f"{eval_cer:.4f} (fraction) = {eval_cer * 100:.1f}% on {n_test} frozen lines ===")

    results_payload = {
        "n_train": n_train,
        "eval_cer": eval_cer,
        "n_test": n_test,
        "seed": seed,
        "splits": str(splits_path.relative_to(REPO)),
    }
    (output_dir / "results.json").write_text(
        json.dumps(results_payload, indent=2), encoding="utf-8"
    )
    print(f"Wrote {(output_dir / 'results.json').relative_to(REPO)}")


if __name__ == "__main__":
    main()
