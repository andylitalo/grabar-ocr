"""Tesseract engines: tess-calfa-n (zero-shot) and tess-grabar (our fine-tune).

Settings are Phase 2's (``predict_lines_tesseract.recognize``): raw-line --psm 13,
--dpi 300, Armenian character whitelist.

    .venv_ml/bin/python -m dev.ocr_eval.run_tesseract --model hye-calfa-n
    .venv_ml/bin/python -m dev.ocr_eval.run_tesseract --model hye-grabar
"""

from __future__ import annotations

import argparse
import sys

from PIL import Image

from .common import REPO_ROOT, add_set_arg, run, use_set

sys.path.insert(0, str(REPO_ROOT / "ml_vision" / "scripts"))
from predict_lines_tesseract import recognize  # noqa: E402

ENGINES = {"hye-calfa-n": "tess-calfa-n", "hye-grabar": "tess-grabar"}
PSM = 13


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(ENGINES), required=True)
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--workers", type=int, default=8, help="parallel tesseract processes")
    add_set_arg(ap)
    a = ap.parse_args()
    use_set(a.set)
    settings = {"lang": a.model, "psm": PSM, "dpi": 300, "whitelist": True}
    run(ENGINES[a.model], settings,
        lambda png: recognize(Image.open(png), PSM, a.model, whitelist=True),
        only_missing=not a.redo, workers=a.workers)


if __name__ == "__main__":
    main()
