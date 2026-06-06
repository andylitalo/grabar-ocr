"""
Offline prediction pass — the single inference step that feeds three consumers:
the error-analysis report (analyze_errors.py), the per-example loss attribution,
and the labeling app's read-only Review view. The app NEVER runs the model; it
only reads what this script writes under data/predictions/.

Loads a fine-tuned TrOCR checkpoint and runs PENALTY-FREE generation (greedy and
beam-4, reusing grabar_generation.configure_generation / NUM_BEAMS — see that
module's hard-won lesson on why repetition penalties hurt). Targets:

  --frozen            -> data/frozen_test_set/line_*.png   (the 100-line eval set)
  --page page_XXXX    -> data/lines/page_XXXX/column_{1,2}/line_*.png

Writes per-line prediction text plus a predictions.json manifest:

  frozen: data/predictions/<tag>/frozen_test_set/line_NNN.txt
  page:   data/predictions/<tag>/page_XXXX/column_Y/line_NNN.txt

<tag> defaults to "scale_500". predictions.json records the model tag, checkpoint
path, timestamp, and per-line pred_greedy / pred_beam.

Run (ML env): call the .venv_ml interpreter directly. Do NOT use
`uv run --python .venv_ml` — uv ignores .venv_ml's site-packages and instead
syncs the base .venv (which has no torch), so the run fails with ModuleNotFound.
    .venv_ml/bin/python ml_vision/scripts/predict_lines.py --frozen
    .venv_ml/bin/python ml_vision/scripts/predict_lines.py --page page_0550
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

sys.path.insert(0, str(Path(__file__).parent))
from grabar_generation import NUM_BEAMS, configure_generation

REPO = Path(__file__).resolve().parent.parent.parent
BASE_ID = "microsoft/trocr-base-printed"
DEFAULT_CKPT_DIR = REPO / "ml_vision/checkpoints/finetune_phase4_scale_500"
FROZEN_DIR = REPO / "data/frozen_test_set"
LINES_DIR = REPO / "data/lines"
PRED_BASE = REPO / "data/predictions"


def pick_checkpoint(ckpt_dir: Path) -> Path:
    """Best checkpoint in a run dir: prefer trainer_state best_model_checkpoint,
    else the kept checkpoint with the lowest best_metric, else the newest."""
    if (ckpt_dir / "config.json").exists():
        return ckpt_dir  # already a concrete checkpoint
    checkpoints = sorted(ckpt_dir.glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1]))
    if not checkpoints:
        raise SystemExit(f"No checkpoint-* dirs under {ckpt_dir}")

    best_path: Path | None = None
    best_metric = float("inf")
    for ck in checkpoints:
        state_path = ck / "trainer_state.json"
        if not state_path.exists():
            continue
        state = json.loads(state_path.read_text(encoding="utf-8"))
        # The recorded best may point at a checkpoint that's still on disk.
        recorded = state.get("best_model_checkpoint")
        if recorded and Path(recorded).exists():
            return Path(recorded)
        metric = state.get("best_metric")
        if metric is not None and metric < best_metric:
            best_metric, best_path = metric, ck
    return best_path or checkpoints[-1]


def collect_frozen() -> list[dict]:
    """Flat frozen lines: id=line_NNN, no column."""
    targets: list[dict] = []
    for png in sorted(FROZEN_DIR.glob("line_*.png")):
        targets.append({"id": png.stem, "column": None, "rel": png.stem, "png": png})
    return targets


def collect_page(page_id: str) -> list[dict]:
    """Page lines across column_* subdirs (placed crops only, mirrors training)."""
    page_dir = LINES_DIR / page_id
    if not page_dir.is_dir():
        raise SystemExit(f"No such page dir: {page_dir.relative_to(REPO)}")
    targets: list[dict] = []
    for col_dir in sorted(page_dir.glob("column_*")):
        col = int(col_dir.name.split("_")[1])
        for png in sorted(col_dir.glob("line_*.png")):
            targets.append(
                {
                    "id": f"column_{col}/{png.stem}",
                    "column": col,
                    "rel": f"column_{col}/{png.stem}",
                    "png": png,
                }
            )
    if not targets:
        raise SystemExit(f"No line_*.png under {page_dir.relative_to(REPO)}/column_*")
    return targets


def generate(model, processor, image: Image.Image, device: str, beam: bool) -> str:
    pixel_values = processor(images=image, return_tensors="pt").pixel_values.to(device)
    kwargs = {"max_length": 64}
    if beam:
        kwargs["num_beams"] = NUM_BEAMS
    with torch.no_grad():
        ids = model.generate(pixel_values, **kwargs)
    return processor.batch_decode(ids, skip_special_tokens=True)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--frozen", action="store_true", help="predict the frozen 100-line test set")
    g.add_argument("--page", type=str, help="predict a page, e.g. page_0550 (reads data/lines/)")
    parser.add_argument("--model-tag", default="scale_500", help="output subdir tag (default: scale_500)")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CKPT_DIR,
        help="checkpoint dir or run dir (default: finetune_phase4_scale_500, best auto-picked)",
    )
    args = parser.parse_args()

    ckpt = pick_checkpoint(args.checkpoint if args.checkpoint.is_absolute() else REPO / args.checkpoint)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Checkpoint: {ckpt.relative_to(REPO) if ckpt.is_relative_to(REPO) else ckpt}")
    print(f"Device    : {device}")

    processor = TrOCRProcessor.from_pretrained(BASE_ID)
    model = VisionEncoderDecoderModel.from_pretrained(ckpt).to(device)
    model.eval()
    configure_generation(model)  # penalty-free decoding (see grabar_generation.py lesson)

    if args.frozen:
        targets = collect_frozen()
        page_key = "frozen_test_set"
    else:
        targets = collect_page(args.page)
        page_key = args.page

    out_dir = PRED_BASE / args.model_tag / page_key
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Predicting {len(targets)} lines -> {out_dir.relative_to(REPO)}/\n")
    lines_payload: dict[str, dict] = {}
    for i, t in enumerate(targets, start=1):
        image = Image.open(t["png"]).convert("RGB")
        pred_greedy = generate(model, processor, image, device, beam=False)
        pred_beam = generate(model, processor, image, device, beam=True)

        txt_out = out_dir / f"{t['rel']}.txt"
        txt_out.parent.mkdir(parents=True, exist_ok=True)
        txt_out.write_text(pred_beam + "\n", encoding="utf-8")  # beam is the headline prediction

        lines_payload[t["id"]] = {
            "column": t["column"],
            "pred_greedy": pred_greedy,
            "pred_beam": pred_beam,
        }
        if i % 20 == 0 or i == len(targets):
            print(f"  {i}/{len(targets)}")

    manifest = {
        "model_tag": args.model_tag,
        "checkpoint": str(ckpt.relative_to(REPO) if ckpt.is_relative_to(REPO) else ckpt),
        "base_id": BASE_ID,
        "target": page_key,
        "num_beams": NUM_BEAMS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lines": lines_payload,
    }
    (out_dir / "predictions.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {(out_dir / 'predictions.json').relative_to(REPO)}  ({len(lines_payload)} lines)")


if __name__ == "__main__":
    main()
