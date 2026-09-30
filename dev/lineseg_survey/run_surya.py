"""Surya line detection (+ fast layout for reading order) → survey geometry.

Runs in its own venv:

    dev/lineseg_survey/.venv-surya/bin/python dev/lineseg_survey/run_surya.py [--pages 453-643]

Surya's detector returns 4-point polygons + confidence, no baselines and no reading
order. Order comes from Surya's rf-detr fast-layout blocks (``position``) via
``common.order_by_blocks``; baselines are stand-ins (``common.midline_baseline``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

from surya.detection import DetectionPredictor  # noqa: E402
from surya.fast_layout import FastLayoutPredictor  # noqa: E402

TOOL = "surya"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", help="e.g. 453-643 or 457,530 (default: survey sample)")
    args = ap.parse_args()

    det = DetectionPredictor.local()
    layout = FastLayoutPredictor()

    for page in common.parse_pages(args.pages):
        src = common.render_path(page)
        if not src.exists():
            print(f"page {page}: no render, skipped")
            continue
        image = Image.open(src).convert("RGB")
        [det_res] = det([image])
        [lay_res] = layout([image])

        lines = []
        for pb in det_res.bboxes:
            poly = [[float(x), float(y)] for x, y in pb.polygon]
            box = common.bbox_of(poly)
            lines.append({
                "boundary": poly,
                "baseline": common.midline_baseline(box),
                "bbox": box,
                "confidence": round(float(pb.confidence or 0.0), 4),
            })
        blocks = [
            {"bbox": [float(v) for v in b.bbox], "position": b.position, "label": b.label}
            for b in lay_res.bboxes
        ]
        ordered = common.order_by_blocks(lines, blocks)
        path = common.write_segmentation(
            TOOL, page, ordered,
            width=image.width, height=image.height,
            model="surya detection + fast_layout",
            extra={"layout_blocks": blocks},
        )
        print(f"page {page}: {len(ordered)} lines, {len(blocks)} blocks → {path.relative_to(common.REPO_ROOT)}")


if __name__ == "__main__":
    main()
