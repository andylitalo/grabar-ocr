"""
Unit tests for the Phase 6 region identity model (labeling_ui.storage) and the
one-shot column_N -> region_NN_<type> migrator (data_prep.migrate_region_names).

Pure filesystem + JSON: no cv2 / torch, runs in the BASE env.
"""

from __future__ import annotations

import json

import pytest

from data_prep import migrate_region_names as mig
from labeling_ui import storage


# --- region naming / parsing -------------------------------------------------


def test_region_dirname_roundtrip():
    assert storage.region_dirname(1, "left") == "region_01_left"
    assert storage.region_dirname(2, "right") == "region_02_right"
    assert storage.region_dirname(10, "single") == "region_10_single"
    with pytest.raises(ValueError):
        storage.region_dirname(1, "footnote")


def test_parse_region_handles_region_and_legacy_and_junk():
    assert storage.parse_region("region_01_left") == (1, "left")
    assert storage.parse_region("region_03_header") == (3, "header")
    # legacy column dirs map to ordered left/right
    assert storage.parse_region("column_1") == (1, "left")
    assert storage.parse_region("column_2") == (2, "right")
    # not a region dir
    assert storage.parse_region("rejected") is None
    assert storage.parse_region("boxes") is None


def test_line_id_for():
    assert storage.line_id_for("region_02_left", 7) == "region_02_left/line_007"


def test_region_dirs_in_reading_order(tmp_path):
    page = tmp_path / "page_0001_auto"
    # create out of order; non-region dirs must be ignored
    for name in ("region_02_right", "region_01_left", "region_03_single", "boxes"):
        (page / name).mkdir(parents=True)
    ordered = [d.name for d in storage.region_dirs_in(page)]
    assert ordered == ["region_01_left", "region_02_right", "region_03_single"]


def test_region_dirs_in_legacy_columns(tmp_path):
    page = tmp_path / "page_0002_human"
    for name in ("column_2", "column_1"):
        (page / name).mkdir(parents=True)
    ordered = [d.name for d in storage.region_dirs_in(page)]
    assert ordered == ["column_1", "column_2"]


# --- list_lines over region dirs (storage.DATA_LINES monkeypatched) ----------


def _write_line(region_dir, line, text=None):
    region_dir.mkdir(parents=True, exist_ok=True)
    (region_dir / f"line_{line:03d}.png").write_bytes(b"\x89PNG")
    if text is not None:
        (region_dir / f"line_{line:03d}.txt").write_text(text, encoding="utf-8")


def test_list_lines_orders_and_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_LINES", tmp_path)
    monkeypatch.setattr(storage, "DATA_PREDICTIONS", tmp_path / "nope")
    page = tmp_path / "page_0003_auto"
    _write_line(page / "region_02_left", 1, "ա")
    _write_line(page / "region_03_right", 1)  # pending (no txt)
    _write_line(page / "region_01_header", 1, "ՎԵՐՆԱԳԻՐ")

    info = storage.list_lines("page_0003_auto")
    ids = [ln["line_id"] for ln in info["lines"]]
    # header (order 01) first, then left (02), then right (03)
    assert ids == [
        "region_01_header/line_001",
        "region_02_left/line_001",
        "region_03_right/line_001",
    ]
    assert info["lines"][0]["region_type"] == "header"
    assert info["lines"][2]["status"] == "pending"
    assert info["counts"]["labeled"] == 2 and info["counts"]["pending"] == 1


# --- migrator ----------------------------------------------------------------


def _build_legacy_tree(root):
    """A method-tagged legacy tree with two-column lines, a column PNG pair,
    a predictions.json, and a nonchar_truth.json — all keyed column_N."""
    lines = root / "data" / "lines" / "page_0001_auto"
    for col in (1, 2):
        d = lines / f"column_{col}"
        d.mkdir(parents=True)
        (d / "line_001.png").write_bytes(b"\x89PNG")
    (lines / "nonchar_truth.json").write_text(
        json.dumps({"page_id": "page_0001_auto", "lines": {
            "column_1/line_001": {"truth": "character"},
            "column_2/line_001": {"truth": "empty"},
        }}), encoding="utf-8")

    cols = root / "data" / "columns"
    cols.mkdir(parents=True)
    for col in (1, 2):
        (cols / f"page_0001_auto_column_{col}.png").write_bytes(b"\x89PNG")

    pred = root / "data" / "predictions" / "scale_500" / "page_0001_auto"
    for col in (1, 2):
        d = pred / f"column_{col}"
        d.mkdir(parents=True)
        (d / "line_001.txt").write_text("x", encoding="utf-8")
    (pred / "predictions.json").write_text(
        json.dumps({"target": "page_0001_auto", "lines": {
            "column_1/line_001": {"column": 1, "pred_beam": "ա"},
            "column_2/line_001": {"column": 2, "pred_beam": "բ"},
        }}), encoding="utf-8")


def _point_migrator_at(root, monkeypatch):
    monkeypatch.setattr(mig, "REPO", root)
    monkeypatch.setattr(mig, "DATA", root / "data")
    monkeypatch.setattr(mig, "LINES", root / "data" / "lines")
    monkeypatch.setattr(mig, "COLUMNS", root / "data" / "columns")
    monkeypatch.setattr(mig, "PREDICTIONS", root / "data" / "predictions")
    monkeypatch.setattr(mig, "BACKUPS", root / "data" / "backups")


def test_migrator_renames_and_repoints(tmp_path, monkeypatch):
    _build_legacy_tree(tmp_path)
    _point_migrator_at(tmp_path, monkeypatch)

    moves = mig.plan_moves()
    repoints = mig.plan_key_repoints()
    # 2 line dirs + 2 column pngs + 2 prediction dirs
    assert len(moves) == 6
    assert len(repoints) == 2  # predictions.json + nonchar_truth.json

    log = mig.apply_migration(moves, repoints)
    assert len(log["moves"]) == 6

    lines = tmp_path / "data" / "lines" / "page_0001_auto"
    assert (lines / "region_01_left" / "line_001.png").exists()
    assert (lines / "region_02_right" / "line_001.png").exists()
    assert not (lines / "column_1").exists()

    cols = tmp_path / "data" / "columns"
    assert (cols / "page_0001_auto_region_01_left.png").exists()
    assert (cols / "page_0001_auto_region_02_right.png").exists()

    pred = tmp_path / "data" / "predictions" / "scale_500" / "page_0001_auto"
    assert (pred / "region_01_left" / "line_001.txt").exists()
    pj = json.loads((pred / "predictions.json").read_text(encoding="utf-8"))
    assert set(pj["lines"]) == {"region_01_left/line_001", "region_02_right/line_001"}

    truth = json.loads((lines / "nonchar_truth.json").read_text(encoding="utf-8"))
    assert set(truth["lines"]) == {"region_01_left/line_001", "region_02_right/line_001"}


def test_migrator_is_idempotent(tmp_path, monkeypatch):
    _build_legacy_tree(tmp_path)
    _point_migrator_at(tmp_path, monkeypatch)
    mig.apply_migration(mig.plan_moves(), mig.plan_key_repoints())
    # second pass: nothing left to do
    assert mig.plan_moves() == []
    assert mig.plan_key_repoints() == []
