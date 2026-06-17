"""
auto_slice.py
Headless column slicing for normal two-column pages.

For each page: render + deskew (cached), detect the two columns by vertical
projection, and — when the detector is confident — crop the columns and segment
them into line PNGs by reusing the labeling pipeline unchanged. Pages that are not
a clean two-column layout are skipped and logged (edge cases handled later), never
mis-cropped.

Reuses:
  - labeling_ui.pipeline.render_page / crop_columns_and_lines
  - data_prep.column_detector.detect_columns
  - labeling_ui.storage  (paths, label guard, box persistence)

Usage:
    python -m data_prep.auto_slice --pages 51,200,400
    python -m data_prep.auto_slice --range 100-120
    python -m data_prep.auto_slice --all --dry-run
    python -m data_prep.auto_slice --pages 51 --force      # re-slice a labeled page
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from data_prep.column_detector import detect_columns  # noqa: E402
from labeling_ui import pipeline, storage  # noqa: E402

logger = logging.getLogger("auto_slice")


def auto_slice_page(n: int, *, persist_boxes: bool = True, dry_run: bool = False, force: bool = False) -> dict:
    """Detect columns for page n and (unless dry-run) crop columns + lines.

    Returns a result dict: ``{"page_id", "confident", "reason", "boxes", ...}``.
    When not confident, nothing is written and the page is reported as deferred.
    """
    page_id = storage.page_id_for(n)
    render_path = pipeline.render_page(n)
    gray = cv2.imread(str(render_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(f"Cannot read render: {render_path}")

    boxes, diag = detect_columns(gray)
    result = {"page_id": page_id, "confident": bool(diag.get("confident")), "reason": diag.get("reason", ""), "boxes": boxes}
    if not result["confident"]:
        logger.info("%s: DEFER — %s", page_id, result["reason"])
        return result

    if persist_boxes:
        storage.save_boxes(page_id, pipeline.deskew_angle(n), boxes, source="auto")

    if dry_run:
        logger.info("%s: confident (dry-run, no crop) boxes=%s", page_id, boxes)
        return result

    labeled = [i for i in (1, 2) if storage.column_has_labels(page_id, i)]
    if labeled and not force:
        result["reason"] = f"has labels in column(s) {labeled}; use --force to re-slice"
        logger.warning("%s: SKIP — %s", page_id, result["reason"])
        return result

    counts = pipeline.crop_columns_and_lines(n, boxes, do_deskew=True)
    result["line_counts"] = counts
    logger.info("%s: sliced %s", page_id, counts)
    return result


def _parse_pages(args: argparse.Namespace) -> list[int]:
    if args.all:
        return storage.list_page_numbers()
    if args.range:
        lo, hi = (int(x) for x in args.range.split("-", 1))
        return list(range(lo, hi + 1))
    if args.pages:
        return [int(x) for x in args.pages.split(",") if x.strip()]
    raise SystemExit("Specify one of --pages, --range, or --all")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Headless two-column slicing")
    parser.add_argument("--pages", help="Comma-separated page numbers, e.g. 51,200,400")
    parser.add_argument("--range", help="Inclusive page range, e.g. 100-120")
    parser.add_argument("--all", action="store_true", help="All pages under data/pages/")
    parser.add_argument("--dry-run", action="store_true", help="Detect + record boxes only; no crops")
    parser.add_argument("--force", action="store_true", help="Re-slice pages that already have labels")
    args = parser.parse_args()

    pages = _parse_pages(args)
    confident = deferred = sliced = 0
    for n in pages:
        if not storage.page_pdf_path(n).exists():
            logger.warning("page %d: no PDF, skipping", n)
            continue
        res = auto_slice_page(n, dry_run=args.dry_run, force=args.force)
        if res["confident"]:
            confident += 1
            if "line_counts" in res:
                sliced += 1
        else:
            deferred += 1

    logger.info(
        "\nDone: %d pages | confident=%d deferred=%d sliced=%d%s",
        len(pages), confident, deferred, sliced, " (dry-run)" if args.dry_run else "",
    )


if __name__ == "__main__":
    main()
