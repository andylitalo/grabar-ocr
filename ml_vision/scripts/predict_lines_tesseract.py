"""
Phase 2 follow-up — hye-tesseract line-level OCR pass, schema-identical to
predict_lines.py so analyze_errors.py scores it UNCHANGED.

A one-off benchmark (not a production backend): instead of a fine-tuned TrOCR
checkpoint, this runs plain Tesseract-OCR with calfa-co/hye-tesseract's
`hye-calfa-n` traineddata (Classical/Western/Eastern Armenian incl. historical
fonts) over the same line crops, then writes the same predictions.json schema
{lines[id] = {column, pred_greedy, pred_beam}} under a new model tag.

Tesseract has no greedy/beam split, so the single recognized string is written
into BOTH pred_greedy and pred_beam (so the existing report's "beam" column is
the apples-to-apples headline number against TrOCR's beam).

PSM (page-segmentation mode) matters for line crops: empirically PSM 13
(raw line, no Tesseract layout heuristics) recognizes these crops reliably,
while PSM 7 (single text line) silently returns empty on many of them. PSM 13
is the default; pass --psm 7 to A/B.

Targets mirror predict_lines.py:
  --frozen            -> data/frozen_test_set/line_*.png   (the 100-line eval set)
  --page page_XXXX_M  -> data/lines/page_XXXX_M/column_{1,2}/line_*.png

Writes (mirrors the TrOCR script, under tag "tesseract" by default):
  frozen: data/predictions/<tag>/frozen_test_set/line_NNN.txt
  page:   data/predictions/<tag>/page_XXXX/column_Y/line_NNN.txt
  + predictions.json manifest.

Run (ML env): call the .venv_ml interpreter directly (has pytesseract/jiwer).
Do NOT use `uv run --python .venv_ml`.
    .venv_ml/bin/python ml_vision/scripts/predict_lines_tesseract.py --frozen
    .venv_ml/bin/python ml_vision/scripts/predict_lines_tesseract.py --page page_0400_human

Then score with the EXISTING tool, no changes:
    .venv_ml/bin/python ml_vision/scripts/analyze_errors.py --frozen --model-tag tesseract
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytesseract
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from predict_lines import collect_frozen, collect_page  # reuse identical target globs

REPO = Path(__file__).resolve().parent.parent.parent
TESSDATA = REPO / "ml_vision/tessdata"
LANG = "hye-calfa-n"
PRED_BASE = REPO / "data/predictions"


def recognize(image: Image.Image, psm: int) -> str:
    """Single Tesseract pass over one line crop. --dpi 300 matches the scan DPI;
    --tessdata-dir keeps the traineddata repo-local (out of system dirs)."""
    config = f"--psm {psm} --dpi 300 --tessdata-dir {TESSDATA}"
    return pytesseract.image_to_string(image, lang=LANG, config=config).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--frozen", action="store_true", help="predict the frozen 100-line test set")
    g.add_argument("--page", type=str, help="predict a page, e.g. page_0400_human (reads data/lines/)")
    parser.add_argument("--model-tag", default="tesseract", help="output subdir tag (default: tesseract)")
    parser.add_argument("--psm", type=int, default=13, help="Tesseract page-seg mode (default: 13 raw-line)")
    args = parser.parse_args()

    if not (TESSDATA / f"{LANG}.traineddata").exists():
        raise SystemExit(f"Missing {LANG}.traineddata under {TESSDATA.relative_to(REPO)} (see plan §Setup).")

    print(f"Engine  : tesseract ({pytesseract.get_tesseract_version()}) lang={LANG} psm={args.psm}")

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
    n_empty = 0
    for i, t in enumerate(targets, start=1):
        image = Image.open(t["png"]).convert("RGB")
        pred = recognize(image, args.psm)
        if not pred:
            n_empty += 1

        txt_out = out_dir / f"{t['rel']}.txt"
        txt_out.parent.mkdir(parents=True, exist_ok=True)
        txt_out.write_text(pred + "\n", encoding="utf-8")

        # No greedy/beam split in Tesseract: same string into both fields.
        lines_payload[t["id"]] = {
            "column": t["column"],
            "pred_greedy": pred,
            "pred_beam": pred,
        }
        if i % 20 == 0 or i == len(targets):
            print(f"  {i}/{len(targets)}")

    manifest = {
        "model_tag": args.model_tag,
        "engine": "tesseract",
        "tesseract_version": str(pytesseract.get_tesseract_version()),
        "lang": LANG,
        "psm": args.psm,
        "target": page_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lines": lines_payload,
    }
    (out_dir / "predictions.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {(out_dir / 'predictions.json').relative_to(REPO)}  "
          f"({len(lines_payload)} lines, {n_empty} empty)")


if __name__ == "__main__":
    main()
