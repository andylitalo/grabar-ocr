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
import shlex
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

# --- character whitelist (Armenian script only) ------------------------------
# The hye model occasionally emits stray Latin letters / garbage on decorative or
# low-contrast lines (e.g. a title page yielding "...ՀԱՏՈՐԸek"). Restricting
# recognition to the Armenian script + the punctuation that actually occurs in
# these texts removes that contamination at no quality cost. Built from ranges so
# it's auditable:
#   uppercase Ա(U+0531)–Ֆ(U+0556), lowercase ա(U+0561)–ֆ(U+0586),
#   ligature և(U+0587), Arabic digits 0–9, and the punctuation below.
# Punctuation — requested: ՝ - . ՜ ՚ ։ … ; recommended additions: , (the printed
# text uses ASCII commas between clauses), ՛ ՞ ՟ (emphasis / question / abbreviation
# [patiw] marks — the last is common in Grabar), ֊ (Armenian hyphen, used at
# line-break), « » and ( ) for quotes / parentheses.
# The trailing SPACE is required: in LSTM mode an explicit whitelist drops inter-word
# spaces unless space is whitelisted. pytesseract uses shlex.split on the config
# string, so the space-containing value is passed via shlex.quote (see recognize).
_ARM_UPPER = "".join(chr(c) for c in range(0x0531, 0x0557))
_ARM_LOWER = "".join(chr(c) for c in range(0x0561, 0x0587))
_LIGATURE = "և"  # և
_DIGITS = "0123456789"
_PUNCT = "՝,-.՜՚։…՛՞՟֊«»()"
CHAR_WHITELIST = _ARM_UPPER + _ARM_LOWER + _LIGATURE + _DIGITS + _PUNCT + " "


def recognize(image: Image.Image, psm: int, whitelist: bool = True) -> str:
    """Single Tesseract pass over one line crop. --dpi 300 matches the scan DPI;
    --tessdata-dir keeps the traineddata repo-local (out of system dirs). When
    ``whitelist`` is set, recognition is restricted to CHAR_WHITELIST (Armenian +
    digits + in-use punctuation + space), which strips stray Latin/garbage while
    keeping word spacing."""
    config = f"--psm {psm} --dpi 300 --tessdata-dir {TESSDATA}"
    if whitelist:
        config += " -c " + shlex.quote("tessedit_char_whitelist=" + CHAR_WHITELIST)
        config += " -c preserve_interword_spaces=1"
    return pytesseract.image_to_string(image, lang=LANG, config=config).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--frozen", action="store_true", help="predict the frozen 100-line test set")
    g.add_argument("--page", type=str, help="predict a page, e.g. page_0400_human (reads data/lines/)")
    parser.add_argument("--model-tag", default="tesseract", help="output subdir tag (default: tesseract)")
    parser.add_argument("--psm", type=int, default=13, help="Tesseract page-seg mode (default: 13 raw-line)")
    parser.add_argument("--no-whitelist", action="store_true",
                        help="disable the Armenian-script char whitelist (A/B: allows Latin/garbage)")
    args = parser.parse_args()
    use_whitelist = not args.no_whitelist

    if not (TESSDATA / f"{LANG}.traineddata").exists():
        raise SystemExit(f"Missing {LANG}.traineddata under {TESSDATA.relative_to(REPO)} (see plan §Setup).")

    print(f"Engine  : tesseract ({pytesseract.get_tesseract_version()}) lang={LANG} "
          f"psm={args.psm} whitelist={'on' if use_whitelist else 'off'}")

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
        pred = recognize(image, args.psm, whitelist=use_whitelist)
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
        "char_whitelist": CHAR_WHITELIST if use_whitelist else None,
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
