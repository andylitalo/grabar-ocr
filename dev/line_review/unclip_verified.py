"""Send verified pages back for review with their boxes pushed out over cut letters.

Pages verified before ``unclip`` existed (pp.453-516) still cut about 2,000 letters. For
each verified page this adds the ``unclip`` reshape ops (``"auto": true``) to its review
and sets it to ``fixed``, so the reviewer looks at the clean view and re-verifies it.
Ids are kept: a reshape doesn't change a line's key. Re-verifying rewrites
``data/verified_lines/page_<N>.json``; then run ``migrate repair``, which sets aside the
transcriptions and predictions of the lines whose shape changed.

A page that isn't verified, or already has auto reshapes, is left alone, so a re-run
only reports what's left.

    uv run python -m dev.line_review.unclip_verified 453-516
"""

from __future__ import annotations

import argparse

import cv2

from . import storage, unclip


def reopen(pages: list[int]) -> dict[int, int]:
    """``{page: number of ops added}`` for the pages sent back to ``fixed``."""
    done = {}
    for page in pages:
        review = storage.load_review(page)
        if review["status"] != "verified" or any(
                o.get("op") == "reshape" and o.get("auto") for o in review["ops"]):
            continue
        gray = cv2.imread(str(storage.render_path(page)), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        ops = unclip.auto_ops(storage.materialized(page, review), gray)
        if not ops:
            continue
        # Materialize first (raises OpError): an op rejected by save_ops after the page
        # left `verified` would strand it in `fixing` without them, and a re-run skips it.
        storage.materialized_page(page, review["ops"] + ops, review.get("section_titles", []))
        storage.set_status(page, "fixing")
        storage.save_ops(page, review["ops"] + ops, review.get("section_titles", []))
        storage.set_status(page, "fixed")
        done[page] = len(ops)
    return done


def _pages(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += range(int(a), int(b or a) + 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pages", help="e.g. 453-516 or 453,460-462")
    done = reopen(_pages(ap.parse_args().pages))
    for page, n in done.items():
        print(f"p{page}: {n} boxes extended, now fixed")
    print(f"{len(done)} pages sent back for review, {sum(done.values())} boxes extended")


if __name__ == "__main__":
    main()
