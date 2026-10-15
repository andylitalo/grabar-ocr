"""Rewrite data/verified_lines/ from the reviews, e.g. after the output format changes.

Ids come from the reviews, so they don't change; only pages whose status is
``verified`` are rewritten.

    uv run python -m dev.line_review.rewrite_verified
"""

from __future__ import annotations

from . import materialize as mz
from . import storage


def main() -> None:
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
        if path.exists() and path.read_text() == new:
            continue
        path.write_text(new, encoding="utf-8")
        print(f"page {page}: rewritten")


if __name__ == "__main__":
    main()
