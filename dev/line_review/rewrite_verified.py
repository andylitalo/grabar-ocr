"""Rewrite data/verified_lines/ from the reviews after the output *format* changes.

Ids come from the reviews, so they don't change; only pages whose status is
``verified`` are rewritten. A rewrite that would change what was verified (line ids,
order, keys, geometry, the page number or section titles), e.g. after a change to the
reading-order or geometry code, is refused: the page is listed and left alone, since
nobody has looked at the new result. ``--reopen`` sends those pages back to fixing
(their files are marked ``resumed_at``) so they get re-verified in the review UI.

    uv run python -m dev.line_review.rewrite_verified            # rewrite format-only changes
    uv run python -m dev.line_review.rewrite_verified --reopen   # and reopen changed pages
"""

from __future__ import annotations

import argparse
import json

from . import materialize as mz
from . import storage

LINE_FIELDS = ("id", "order", "key", "boundary", "baseline", "bbox")
PAGE_FIELDS = ("page_number", "section_titles")


def content(record: dict) -> dict:
    """The part of a verified record a reviewer signed off on (not its format)."""
    return {**{f: record.get(f) for f in PAGE_FIELDS},
            "lines": [{f: l.get(f) for f in LINE_FIELDS} for l in record.get("lines", [])]}


def describe(old: dict, new: dict) -> str:
    """A short account of how ``new`` differs from ``old``."""
    before = {l["id"]: l for l in content(old)["lines"]}
    after = {l["id"]: l for l in content(new)["lines"]}
    parts = []
    if gone := sorted(before.keys() - after.keys()):
        parts.append(f"lines gone {gone}")
    if added := sorted(after.keys() - before.keys()):
        parts.append(f"lines added {added}")
    both = before.keys() & after.keys()
    if moved := sorted(i for i in both if before[i]["order"] != after[i]["order"]):
        parts.append(f"{len(moved)} lines reordered")
    reshaped = sorted(i for i in both if any(before[i][f] != after[i][f]
                                            for f in ("key", "boundary", "baseline", "bbox")))
    if reshaped:
        parts.append(f"geometry changed on {reshaped}")
    if any(old.get(f) != new.get(f) for f in PAGE_FIELDS):
        parts.append("page number or section titles changed")
    return "; ".join(parts) or "content changed"


def main(argv: list[str] | None = None) -> int:
    """Returns 1 if any page was refused (and not reopened), else 0."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reopen", action="store_true",
                    help="send pages whose verified content would change back to fixing")
    args = ap.parse_args(argv)
    refused = 0
    for page, status in storage.page_statuses().items():
        if status != "verified":
            continue
        review = storage.load_review(page)
        if storage.baseline_changed(review):
            print(f"page {page}: baseline changed under the review, skipped")
            continue
        record = mz.verified_record(storage.load_baseline(page), review,
                                    baseline_sha256=storage.baseline_sha256(page))
        path = storage.verified_path(page)
        new = mz.dumps(record)
        if path.exists():
            if path.read_text() == new:
                continue
            old = json.loads(path.read_text())
            if content(old) != content(record):
                if args.reopen:
                    storage.set_status(page, "fixing")
                    print(f"page {page}: reopened for review ({describe(old, record)})")
                else:
                    refused += 1
                    print(f"page {page}: NOT rewritten, verified content would change: "
                          f"{describe(old, record)}")
                continue
        path.write_text(new, encoding="utf-8")
        print(f"page {page}: rewritten")
    if refused:
        print(f"{refused} page(s) refused; re-run with --reopen to send them back for review")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
