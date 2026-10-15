"""
Phase 9 gate check: every committed data/verified_lines/page_<N>.json is reproduced
byte for byte by re-materializing paddle-filled + the page's review ops, every verified
review has its file, and a page sent back to fixing has its file marked ``resumed_at``.
"""

from __future__ import annotations

import json

import pytest

from dev.line_review import materialize as mz
from dev.line_review import storage

VERIFIED = sorted(storage.VERIFIED_DIR.glob("page_*.json"))


@pytest.mark.parametrize("path", VERIFIED, ids=[p.stem for p in VERIFIED])
def test_verified_file_reproduces(path):
    record = json.loads(path.read_text())
    page = record["page"]
    review = storage.load_review(page)
    if review["status"] != "verified":
        assert "resumed_at" in record, (
            f"page {page} is {review['status']} but its verified file isn't marked resumed_at")
        return
    assert "resumed_at" not in record, f"page {page} is verified but its file is marked resumed"
    assert not storage.baseline_changed(review), "paddle-filled changed under a verified page"
    record = mz.verified_record(storage.load_baseline(page), review,
                                baseline_sha256=storage.baseline_sha256(page))
    assert mz.dumps(record) == path.read_text()


def test_every_verified_review_has_its_file():
    missing = [p for p, s in storage.page_statuses().items()
               if s == "verified" and not storage.verified_path(p).exists()]
    assert not missing, f"verified reviews with no data/verified_lines file: {missing}"
