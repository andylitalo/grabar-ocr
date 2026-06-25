"""
sample_auto_pages.py — slice a spread of auto pages for Phase A detector validation.

To measure the non-character detector's recall on production-like data, we need a
sample of auto-sliced pages spread across the book (prose, ornament/divider-heavy,
section openers, faded scans) that a human then verifies line-by-line in the
labeling UI's verify-non-character mode.

This wraps data_prep.auto_slice.auto_slice_page over a default spread of page
numbers, skipping the known-broken page_0543 source PDF and reporting which pages
sliced vs. deferred (the detector self-skips low-confidence layouts). No APIs, no
OCR — pure local rendering + slicing.

Run (BASE env):
    .venv/bin/python data_prep/sample_auto_pages.py            # default spread
    uv run python data_prep/sample_auto_pages.py --pages 40,80,120
    uv run python data_prep/sample_auto_pages.py --force       # re-slice
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from data_prep.auto_slice import auto_slice_page  # noqa: E402
from labeling_ui import storage  # noqa: E402

logger = logging.getLogger("sample_auto_pages")

# A spread across the book (1–646): prose, openers, and known ornament/divider
# pages. Includes human-labeled anchors (200, 400, 487) for cross-checking and
# the auto pages already present (486, 487). page_0543 is a broken source PDF.
DEFAULT_SPREAD = [
    40, 80, 120, 160, 200, 240, 280, 320, 360, 400, 440,
    480, 486, 487, 520, 560, 600, 640,
]
SKIP_PAGES = {543}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", help="comma-separated page numbers (default: built-in spread)")
    ap.add_argument("--force", action="store_true", help="re-slice pages that already have crops/labels")
    args = ap.parse_args()

    if args.pages:
        pages = [int(x) for x in args.pages.split(",") if x.strip()]
    else:
        pages = DEFAULT_SPREAD

    sliced: list[str] = []
    deferred: list[str] = []
    missing: list[int] = []
    for n in pages:
        if n in SKIP_PAGES:
            logger.info("page %d: SKIP (known-broken source)", n)
            continue
        if not storage.page_pdf_path(n).exists():
            logger.warning("page %d: no PDF, skipping", n)
            missing.append(n)
            continue
        res = auto_slice_page(n, force=args.force)
        if res.get("confident") and "line_counts" in res:
            total = sum(c["line_count"] for c in res["line_counts"])
            sliced.append(res["page_id"])
            logger.info("%s: sliced %d lines", res["page_id"], total)
        elif res.get("confident"):
            # confident but not sliced (already had labels, no --force)
            deferred.append(res["page_id"])
            logger.info("%s: SKIP — %s", res["page_id"], res.get("reason", ""))
        else:
            deferred.append(res["page_id"])
            logger.info("%s: DEFER — %s", res["page_id"], res.get("reason", ""))

    logger.info(
        "\nDone: %d requested · %d sliced · %d deferred/skipped · %d missing",
        len(pages), len(sliced), len(deferred), len(missing),
    )
    logger.info("\nVerify these in the labeling UI (Verify auto slice), then run:")
    logger.info("  uv run python data_prep/score_nonchar_detector.py")
    if sliced:
        logger.info("\nReady to verify:")
        for pid in sliced:
            logger.info("  %s", pid)


if __name__ == "__main__":
    main()
