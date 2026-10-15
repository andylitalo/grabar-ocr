"""Rewrite data/verified_lines/ from the reviews, e.g. after the output format changes.

Ids come from the reviews, so they don't change; only pages whose status is
``verified`` are rewritten. A line the materializer no longer produces (a copy of a
line Paddle boxed twice, now dropped) has its id retired in the review, as a delete
at verification would.

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
        state = mz.mint_ids(page, storage.materialized(page, review), review)
        if state["ids"] != review.get("ids"):
            review.update(state)
            storage._write_review(review)
            print(f"page {page}: retired {sorted(set(review['retired']) - set(state['ids'].values()))}")
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
