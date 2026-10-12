"""The shipping projection slicer (the survey's control) → survey geometry.

Same code path as ``data_prep.auto_slice``: ``detect_regions`` finds typed text
regions, then each region is cut into lines by horizontal projection
(``strip_vertical_rules`` + ``find_line_boundaries``). Lines are full region-width,
axis-aligned boxes.

Two deliberate differences from production, both noted in the Phase 8 results:
- it runs on the shared kraken render, *not* the deskewed ``page_deskew.png``, so
  every tool sees the same pixels;
- a page the detector is not confident on is recorded with **zero lines** and
  ``deferred: true``. In production those pages went to a human crop, so for this
  control a deferral means "needs a person", which is what the survey measures.

    .venv/bin/python dev/lineseg_survey/run_projection.py [--pages ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

sys.path.insert(0, str(common.REPO_ROOT))
from data_prep.column_detector import detect_regions  # noqa: E402
from data_prep.line_cropper import (  # noqa: E402
    find_line_boundaries,
    horizontal_projection,
    strip_vertical_rules,
)

TOOL = "projection"
PAD = 4  # same padding crop_lines adds above/below a line


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", help="e.g. 453-643 or 457,530 (default: survey sample)")
    args = ap.parse_args()

    for page in common.parse_pages(args.pages):
        src = common.render_path(page)
        if not src.exists():
            print(f"page {page}: no render, skipped")
            continue
        gray = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
        h, w = gray.shape
        regions, diag = detect_regions(gray)
        lines: list[dict] = []
        if diag.get("confident"):
            for r in regions:  # already in reading order
                x1, y1, x2, y2 = (int(r[k]) for k in ("x1", "y1", "x2", "y2"))
                crop = gray[y1:y2, x1:x2]
                for top, bottom in find_line_boundaries(horizontal_projection(strip_vertical_rules(crop))):
                    box = [float(x1), float(max(y1, y1 + top - PAD)),
                           float(x2), float(min(y2, y1 + bottom + PAD))]
                    lines.append({
                        "boundary": common.box_polygon(box),
                        "baseline": common.midline_baseline(box),
                        "bbox": box,
                    })
        path = common.write_segmentation(
            TOOL, page, lines, width=w, height=h,
            model="projection slicer (data_prep)",
            extra={
                "deferred": not diag.get("confident"),
                "defer_reason": diag.get("reason", ""),
                "layout_blocks": [
                    {"bbox": [float(r[k]) for k in ("x1", "y1", "x2", "y2")],
                     "position": i, "label": r["type"]}
                    for i, r in enumerate(regions)
                ],
            },
        )
        note = "" if diag.get("confident") else f"  DEFERRED: {diag.get('reason')}"
        print(f"page {page}: {len(lines)} lines, {len(regions)} regions{note}")


if __name__ == "__main__":
    main()
