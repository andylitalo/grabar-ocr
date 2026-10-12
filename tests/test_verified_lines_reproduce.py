"""
Phase 9 gate check: every committed data/verified_lines/page_<N>.json is reproduced
byte for byte by re-materializing paddle-filled + the page's review ops.
"""

from __future__ import annotations

import json

import pytest

from dev.line_review import materialize as mz
from dev.line_review import storage

VERIFIED = sorted(storage.VERIFIED_DIR.glob("page_*.json"))


@pytest.mark.parametrize("path", VERIFIED, ids=[p.stem for p in VERIFIED])
def test_verified_file_reproduces(path):
    page = json.loads(path.read_text())["page"]
    review = storage.load_review(page)
    if review["status"] != "verified":
        pytest.skip(f"page {page} is back in {review['status']}; re-verify to refresh")
    assert not storage.baseline_changed(review), "paddle-filled changed under a verified page"
    record = mz.verified_record(storage.load_baseline(page), review,
                                baseline_sha256=storage.baseline_sha256(page))
    assert mz.dumps(record) == path.read_text()
