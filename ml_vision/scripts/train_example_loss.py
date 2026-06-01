"""
Per-example training-loss attribution for the final scale_500 model.

Runs the trained model over its OWN 500 training lines (splits_500.json) and
records, per example, the teacher-forced cross-entropy loss (a forward pass WITH
labels — distinct from generation) and the greedy CER. Ranked by loss, this
surfaces the lines the model fits worst: hard fonts, likely mislabels, and the
known multi-line crops (reports/phase_4_results.md notes 2/90 in page_0543,
1/91 in page_0559).

This is cheap loss attribution, NOT influence-on-test (TracIn) — that heavier
analysis is a deliberate follow-up.

Output: reports/phase4_train_example_loss.csv (ranked loss-desc).

Run (ML env):
    uv run --python .venv_ml python ml_vision/scripts/train_example_loss.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import torch
from PIL import Image
from jiwer import cer
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

sys.path.insert(0, str(Path(__file__).parent))
from grabar_generation import configure_generation
from predict_lines import pick_checkpoint

REPO = Path(__file__).resolve().parent.parent.parent
BASE_ID = "microsoft/trocr-base-printed"
PHASE4_DIR = REPO / "data/phase4_dataset"
SPLITS_500 = REPO / "data/phase4_scaling/splits_500.json"
DEFAULT_CKPT_DIR = REPO / "ml_vision/checkpoints/finetune_phase4_scale_500"
OUT_CSV = REPO / "reports/phase4_train_example_loss.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits", type=Path, default=SPLITS_500)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CKPT_DIR)
    args = parser.parse_args()

    ckpt = pick_checkpoint(args.checkpoint if args.checkpoint.is_absolute() else REPO / args.checkpoint)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Checkpoint: {ckpt.relative_to(REPO) if ckpt.is_relative_to(REPO) else ckpt}")
    print(f"Device    : {device}")

    processor = TrOCRProcessor.from_pretrained(BASE_ID)
    model = VisionEncoderDecoderModel.from_pretrained(ckpt).to(device)
    model.eval()
    configure_generation(model)

    split = json.loads(args.splits.read_text(encoding="utf-8"))
    train_ids = split["train"]
    print(f"Scoring {len(train_ids)} training lines from {args.splits.relative_to(REPO)}\n")

    rows: list[dict] = []
    pad_id = processor.tokenizer.pad_token_id
    for i, line_id in enumerate(train_ids, start=1):
        txt_path = PHASE4_DIR / f"{line_id}.txt"
        ref = txt_path.read_text(encoding="utf-8").strip()
        png = txt_path.with_suffix(".png")
        if not ref or not png.exists():
            continue
        page = line_id.split("/")[0]

        image = Image.open(png).convert("RGB")
        pixel_values = processor(images=image, return_tensors="pt").pixel_values.to(device)
        labels = processor.tokenizer(
            ref, padding="max_length", max_length=64, truncation=True, return_tensors="pt"
        ).input_ids
        labels[labels == pad_id] = -100
        labels = labels.to(device)

        with torch.no_grad():
            # Teacher-forced cross-entropy over this example's target tokens.
            loss = model(pixel_values=pixel_values, labels=labels).loss.item()
            gen_ids = model.generate(pixel_values, max_length=64)
        pred = processor.batch_decode(gen_ids, skip_special_tokens=True)[0]

        rows.append(
            {
                "id": line_id,
                "source_page": page,
                "loss": round(loss, 4),
                "cer": round(cer(ref, pred), 4),
                "ref_len": len(ref),
                "multiline": "\n" in txt_path.read_text(encoding="utf-8").strip(),
                "ref": ref.replace("\n", "\\n"),
                "pred": pred,
            }
        )
        if i % 50 == 0 or i == len(train_ids):
            print(f"  {i}/{len(train_ids)}")

    rows.sort(key=lambda r: -r["loss"])
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["id", "source_page", "loss", "cer", "ref_len", "multiline", "ref", "pred"]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    mean_loss = sum(r["loss"] for r in rows) / len(rows)
    n_multi = sum(1 for r in rows if r["multiline"])
    print(f"\nScored {len(rows)} lines · mean loss {mean_loss:.4f} · {n_multi} multi-line crops")
    print(f"Worst 10 by loss:")
    for r in rows[:10]:
        flag = " [multiline]" if r["multiline"] else ""
        print(f"  loss {r['loss']:6.3f}  cer {r['cer']:.3f}  {r['id']}{flag}")
        print(f"      REF {r['ref']!r}")
        print(f"      PRD {r['pred']!r}")
    print(f"\nWrote {OUT_CSV.relative_to(REPO)}")


if __name__ == "__main__":
    main()
