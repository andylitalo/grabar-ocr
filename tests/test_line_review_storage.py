"""
Tests for the Phase 9 review storage (dev.line_review.storage): page status
transitions, the baseline-changed guard, and verify -> data/verified_lines output.

Each test points the module's paths at a tmp dir holding one synthetic baseline.
"""

from __future__ import annotations

import json

import pytest

from dev.line_review import materialize as mz
from dev.line_review import storage


def rect(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    base = tmp_path / "baseline"
    (base / "page_500").mkdir(parents=True)
    seg = {"page": 500, "tool": "paddle-filled", "width": 2000, "height": 3000, "lines": [
        {"id": f"line_00{i}", "boundary": rect(100, 100 * i, 900, 100 * i + 50),
         "baseline": [[100, 100 * i + 37.5], [900, 100 * i + 37.5]],
         "bbox": [100, 100 * i, 900, 100 * i + 50], "source": "hyocr-paddle"}
        for i in range(1, 4)]}
    (base / "page_500" / "segmentation.json").write_text(json.dumps(seg))
    monkeypatch.setattr(storage, "BASELINE_DIR", base)
    monkeypatch.setattr(storage, "REVIEWS_DIR", tmp_path / "reviews")
    monkeypatch.setattr(storage, "VERIFIED_DIR", tmp_path / "verified")
    monkeypatch.setattr(storage, "BLANK_DIR", tmp_path / "blank")
    return tmp_path


def test_unreviewed_page_has_a_fresh_review(tmp_store):
    review = storage.load_review(500)
    assert review["status"] == "unreviewed"
    assert storage.page_statuses() == {500: "unreviewed"}


def test_saving_ops_moves_page_to_fixing(tmp_store):
    review, lines = storage.save_ops(500, [{"op": "delete", "line": "line_002"}], [])
    assert review["status"] == "fixing"
    assert [l["key"] for l in lines] == ["line_001", "line_003"]
    assert storage.page_statuses() == {500: "fixing"}


def test_invalid_ops_are_not_saved(tmp_store):
    with pytest.raises(mz.OpError):
        storage.save_ops(500, [{"op": "delete", "line": "line_404"}], [])
    assert not storage.review_path(500).exists()


def test_fix_then_verify_writes_reproducible_output(tmp_store):
    storage.save_ops(500, [{"op": "delete", "line": "line_002"}], [])
    storage.set_status(500, "fixed")
    review = storage.set_status(500, "verified")
    assert review["ids"] == {"line_001": "p500.001", "line_003": "p500.002"}
    written = storage.verified_path(500).read_text()
    again = mz.dumps(mz.verified_record(storage.load_baseline(500), review,
                                        baseline_sha256=storage.baseline_sha256(500)))
    assert written == again


def test_page_with_no_edits_can_be_fixed_directly(tmp_store):
    assert storage.set_status(500, "fixed")["status"] == "fixed"


def test_verify_requires_fixed_first(tmp_store):
    with pytest.raises(storage.StateError):
        storage.set_status(500, "verified")


def test_edits_need_resume_fixing_after_fixed(tmp_store):
    storage.set_status(500, "fixed")
    with pytest.raises(storage.StateError):
        storage.save_ops(500, [], [])
    storage.set_status(500, "fixing")
    assert storage.save_ops(500, [], [])[0]["status"] == "fixing"


def test_reverify_keeps_ids(tmp_store):
    storage.set_status(500, "fixed")
    first = storage.set_status(500, "verified")["ids"]
    storage.set_status(500, "fixing")
    storage.save_ops(500, [{"op": "add", "key": "add_001", "boundary": rect(100, 160, 900, 190)}], [])
    storage.set_status(500, "fixed")
    second = storage.set_status(500, "verified")["ids"]
    assert all(second[k] == v for k, v in first.items())
    assert second["add_001"] == "p500.004"


def test_changed_baseline_blocks_edits(tmp_store):
    storage.save_ops(500, [], [])
    path = storage.baseline_path(500)
    seg = json.loads(path.read_text())
    seg["lines"].pop()
    path.write_text(json.dumps(seg))
    with pytest.raises(storage.StateError):
        storage.save_ops(500, [], [])
    with pytest.raises(storage.StateError):
        storage.set_status(500, "fixed")
