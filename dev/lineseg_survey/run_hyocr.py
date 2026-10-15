"""Calfa ``hye-open-ocr`` line geometry → survey geometry.

``hye-open-ocr`` has no line detector of its own: its layout stage finds regions and
the recognizer segments lines inside each region. So the pipeline's line boxes are a
fair test of what its lines would look like. Two configurations:

- ``hyocr-tess``   DocLayout-YOLO regions + Tesseract ``--psm 4`` (hye-calfa-n)
                   line finding. Axis-aligned boxes. The pipeline's default.
- ``hyocr-paddle`` PP-DocLayoutV3 regions + PaddleOCR text *detection* (DB) inside
                   each region. Quad polygons. This also covers "PaddleOCR's
                   detector" from the Phase 8 candidate list.

Recognition runs too (it is how the lines are produced) but the text is only kept
as an aid for the reviewer, never scored here.

    dev/lineseg_survey/.venv-hyocr/bin/python dev/lineseg_survey/run_hyocr.py --config tess [--pages ...]
    # full run, keeping the reviewed sample pages as they are:
    dev/lineseg_survey/.venv-hyocr/bin/python dev/lineseg_survey/run_hyocr.py --config paddle --pages 453-643 --skip-existing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

from armenian_ocr import OcrPipeline  # noqa: E402

TESSDATA = common.REPO_ROOT / "ml_vision" / "tessdata"


def build(config: str) -> OcrPipeline:
    if config == "tess":
        from armenian_ocr.layout_yolo import YoloLayoutEngine
        from armenian_ocr.recognition.tesseract import TesseractRecognizer

        return OcrPipeline(YoloLayoutEngine(), TesseractRecognizer(tessdata_dir=TESSDATA))
    if config == "paddle":
        from armenian_ocr.layout_paddle import PaddleDocLayoutEngine
        from armenian_ocr.recognition.paddle import PaddleRecognizer

        return OcrPipeline(PaddleDocLayoutEngine(), PaddleRecognizer())
    raise SystemExit(f"unknown config {config!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=["tess", "paddle"], required=True)
    ap.add_argument("--pages", help="e.g. 453-643 or 457,530 (default: survey sample)")
    ap.add_argument("--tool", help="output tool name (default hyocr-<config>); use for "
                    "parameter experiments, e.g. with ARMENIAN_OCR_PADDLE_DET_BOX_THRESH set")
    ap.add_argument("--skip-existing", action="store_true",
                    help="leave pages that already have geometry untouched (their reviews "
                         "reference its line ids)")
    args = ap.parse_args()
    tool = args.tool or f"hyocr-{args.config}"
    pipeline = build(args.config)

    for page_no in common.parse_pages(args.pages):
        src = common.render_path(page_no)
        if not src.exists():
            print(f"page {page_no}: no render, skipped")
            continue
        if args.skip_existing and (common.tool_data_dir(tool, page_no) / "segmentation.json").exists():
            print(f"page {page_no}: exists, kept")
            continue
        image = np.array(Image.open(src).convert("RGB"))
        page = pipeline.process_image(image, dpi=300)

        lines = []  # paragraphs are already in the pipeline's reading order
        for para in page.paragraphs:
            for line in para.lines:
                box = [float(v) for v in line.box]
                poly = ([[float(x), float(y)] for x, y in line.poly]
                        if line.poly else common.box_polygon(box))
                lines.append({
                    "boundary": poly,
                    "baseline": common.midline_baseline(box),
                    "bbox": box,
                    "confidence": line.confidence,
                    "text": line.text,
                })
        blocks = [
            {"bbox": [float(v) for v in p.box], "position": i, "label": p.label}
            for i, p in enumerate(page.paragraphs)
        ]
        path = common.write_segmentation(
            tool, page_no, lines,
            width=page.width, height=page.height,
            model=f"hye-open-ocr {args.config}" + (f" ({tool})" if args.tool else ""),
            extra={"layout_blocks": blocks},
        )
        print(f"page {page_no}: {len(lines)} lines, {len(blocks)} regions → {path.relative_to(common.REPO_ROOT)}")


if __name__ == "__main__":
    main()
