"""
Phase 2b — stage the scale_500 training split as tesstrain ground-truth pairs.

tesstrain's Makefile wants, in one ground-truth dir, a `<name>.png` + sibling
`<name>.gt.txt` (a single text line) for every training sample. This script
resolves the SAME 500 train ids TrOCR scale_500 trained on
(`data/phase4_scaling/splits_500.json` -> `train`) against the SAME flat line
dataset (`data/phase4_dataset/<page>/line_NNN.{png,txt}`), using the SAME
empty-GT skip as `finetune_phase4.py:samples_from_splits`, and writes them as
`<page>__<line>.png` / `<page>__<line>.gt.txt` into the GT dir.

Held-out discipline: ONLY the splits_500 train ids are staged. Frozen-set lines
(`data/frozen_test_set/`) and page_0400 are never in that list (verified), so
they cannot leak into training.

Usage (ML env):
    .venv_ml/bin/python ml_vision/scripts/build_tesstrain_gt.py \
        --out ml_vision/tessdata_ft/tesstrain/data/hye-grabar-ground-truth
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PHASE4_DIR = REPO / "data/phase4_dataset"
SPLITS = REPO / "data/phase4_scaling/splits_500.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="tesstrain ground-truth dir (created; cleared of *.png/*.gt.txt first)",
    )
    parser.add_argument(
        "--splits", type=Path, default=SPLITS, help="splits json (default: splits_500.json)"
    )
    args = parser.parse_args()

    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for stale in [*out.glob("*.png"), *out.glob("*.gt.txt")]:
        stale.unlink()

    split = json.loads(args.splits.read_text(encoding="utf-8"))
    train_ids = split["train"]

    # Contamination guard: refuse to stage anything outside the train split.
    bad = [i for i in train_ids if "page_0400" in i or "frozen" in i]
    if bad:
        raise SystemExit(f"Refusing to stage held-out ids found in train split: {bad[:5]}")

    n_staged, n_empty, n_missing, n_joined = 0, 0, 0, 0
    for line_id in train_ids:  # e.g. "page_0499/line_083"
        txt_path = PHASE4_DIR / f"{line_id}.txt"
        png_path = txt_path.with_suffix(".png")
        if not txt_path.exists() or not png_path.exists():
            n_missing += 1
            continue
        text = txt_path.read_text(encoding="utf-8").strip()
        if not text:  # skip empty (section markers / folios), as in training
            n_empty += 1
            continue
        # tesstrain's box generator requires exactly ONE physical line per GT.
        # 2/500 crops store their (single-image-line) GT with an embedded newline;
        # join halves with a space. Minor deviation from TrOCR's raw .strip().
        if "\n" in text:
            text = " ".join(part.strip() for part in text.splitlines())
            n_joined += 1

        name = line_id.replace("/", "__")  # page_0499__line_083
        shutil.copyfile(png_path, out / f"{name}.png")
        (out / f"{name}.gt.txt").write_text(text + "\n", encoding="utf-8")
        n_staged += 1

    print(f"Ground-truth dir : {out.relative_to(REPO)}")
    print(f"Train ids        : {len(train_ids)}")
    print(f"Staged pairs     : {n_staged}")
    print(f"Skipped (empty)  : {n_empty}")
    print(f"Skipped (missing): {n_missing}")
    print(f"Newline-joined   : {n_joined}")


if __name__ == "__main__":
    main()
