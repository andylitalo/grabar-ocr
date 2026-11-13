"""surya: Surya recognition, zero-shot, one line crop per call.

Each crop goes in as a page with a single ``Text`` layout block covering it (block mode).
Full-page mode on a single line crop misreads it (it returned a table of Latin-like
fragments for p457.062). Runs on llama.cpp (``llama-server`` must be on PATH); the first
call spawns the server and loads the model (~5 min).

    dev/lineseg_survey/.venv-surya/bin/python -m dev.ocr_eval.run_surya
"""

from __future__ import annotations

import html
import re

from PIL import Image
from surya.layout.schema import LayoutBox, LayoutResult
from surya.recognition import RecognitionPredictor

from .common import args, run

TAG = re.compile(r"<[^>]+>")


def main() -> None:
    a = args(__doc__)
    rec = RecognitionPredictor()

    def recognize(png) -> str:
        img = Image.open(png).convert("RGB")
        w, h = img.size
        box = LayoutBox(polygon=[[0, 0], [w, 0], [w, h], [0, h]], label="Text", raw_label="Text", position=0)
        (page,) = rec([img], [LayoutResult(bboxes=[box], image_bbox=[0, 0, w, h])], full_page=False)
        text = " ".join(html.unescape(TAG.sub(" ", b.html)) for b in page.blocks)
        return " ".join(text.split())

    run("surya", {"mode": "block", "block": "Text"}, recognize, only_missing=not a.redo)


if __name__ == "__main__":
    main()
