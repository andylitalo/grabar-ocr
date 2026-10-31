"""Rewrite data/verified_lines/ from the reviews after the output *format* changes.

Ids come from the reviews, so they don't change; only pages whose status is
``verified`` are rewritten. A rewrite that would change what was verified (line ids,
order, keys, geometry, initials, sources, the page number or section titles), or whose
ops no longer apply at all, e.g. after a change to the
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

LINE_FIELDS = ("id", "order", "key", "boundary", "baseline", "bbox", "initial", "source",
               "derived_from")
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
    if initials := sorted(i for i in both if before[i]["initial"] != after[i]["initial"]):
        parts.append(f"initial moved or changed on {initials}")
    if sourced := sorted(i for i in both if any(before[i][f] != after[i][f]
                                               for f in ("source", "derived_from"))):
        parts.append(f"source changed on {sourced}")
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
        path = storage.verified_path(page)
        try:
            record = mz.verified_record(storage.load_baseline(page), review,
                                        baseline_sha256=storage.baseline_sha256(page))
        except mz.OpError as e:  # the ops no longer apply, or a line has no id
            record, why = None, f"its ops no longer materialize: {e}"
        new = mz.dumps(record) if record is not None else None
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if old is not None and path.read_text(encoding="utf-8") == new:
            continue
        if record is not None and old is not None and content(old) != content(record):
            why = f"verified content would change: {describe(old, record)}"
        elif record is not None:
            storage.write_atomic(path, new)
            print(f"page {page}: rewritten")
            continue
        if args.reopen:
            storage.set_status(page, "fixing")
            print(f"page {page}: reopened for review ({why})")
        else:
            refused += 1
            print(f"page {page}: NOT rewritten, {why}")
    if refused:
        print(f"{refused} page(s) refused; re-run with --reopen to send them back for review")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
