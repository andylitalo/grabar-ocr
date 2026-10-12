"""
Tests for carrying transcriptions over on verify (dev.line_review.migrate): same-shape
lines move to their new id with sample picks and predictions; edited lines go stale.
"""

from __future__ import annotations

import json

import pytest

from dev.line_review import migrate
from dev.line_review import transcribe as tr


def mline(key: str, y: int, lineage: list[str] = ()) -> dict:
    return {"key": key, "boundary": [[100, y], [900, y], [900, y + 50], [100, y + 50]],
            "lineage": list(lineage)}


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")
    monkeypatch.setattr(migrate, "PREDICTIONS_DIR", tmp_path / "predictions")
    monkeypatch.setattr(migrate, "CROPS_DIR", tmp_path / "runs")
    return tmp_path


def typed(key: str, line: dict, text: str) -> None:
    tr.save_line(key, text=text, status="done", task="ceiling", geometry=tr.geometry(line))


def test_verify_moves_same_shape_lines_and_sets_edited_ones_aside(dirs):
    before = {k: mline(k, y) for k, y in [("line_001", 100), ("line_002", 200),
                                          ("line_003", 300), ("line_004", 400)]}
    for k, text in [("line_001", "Ա"), ("line_002", "Բ"), ("line_003", "Գ"), ("line_004", "Դ")]:
        typed(f"p520~{k}", before[k], text)
    tr.save_sample({"picks": [{"id": f"p520~line_00{i}", "stratum": "agree", "page": 520}
                              for i in range(1, 5)]}, "ceiling")
    pred_dir = dirs / "predictions" / "ceiling"
    pred_dir.mkdir(parents=True)
    keys = [f"p520~line_00{i}" for i in range(1, 5)] + ["p521~line_001"]
    for engine in ("tess-calfa-n", "corr-gemini"):
        (pred_dir / f"{engine}.json").write_text(json.dumps({"lines": {k: k for k in keys}}))

    # Review: line_002 reshaped, line_003 split in two, line_004 deleted.
    after = [mline("line_001", 100), mline("line_002", 205),
             mline("split_001", 300, ["line_003"]), mline("split_002", 325, ["line_003"])]
    ids = {"line_001": "p520.001", "line_002": "p520.002", "split_001": "p520.003", "split_002": "p520.004"}
    summary = migrate.after_verify(520, after, ids)

    assert summary["ceiling"]["moved"] == 1
    assert summary["ceiling"]["stale"] == {"p520~line_002": "shape changed",
                                           "p520~line_003": "line split or merged",
                                           "p520~line_004": "line removed"}
    records = tr.load_page(520, "ceiling")
    assert set(records) == {"p520.001"}
    assert records["p520.001"]["text"] == "Ա" and records["p520.001"]["migrated_from"] == "p520~line_001"
    stale = json.loads((dirs / "transcriptions" / "ceiling" / "stale" / "page_520.json").read_text())
    assert [s["id"] for s in stale] == ["p520~line_002", "p520~line_003", "p520~line_004"]

    sample = tr.load_sample("ceiling")
    assert [p["id"] for p in sample["picks"]] == ["p520.001", "p520.002", "p520.003"]
    assert [p["id"] for p in sample["dropped"]] == ["p520~line_004"]

    plain = json.loads((pred_dir / "tess-calfa-n.json").read_text())["lines"]
    assert plain == {"p520.001": "p520~line_001", "p521~line_001": "p521~line_001"}
    page_level = json.loads((pred_dir / "corr-gemini.json").read_text())["lines"]
    assert page_level == {"p521~line_001": "p521~line_001"}  # page 520 is re-corrected


def test_reverify_with_unchanged_lines_changes_nothing(dirs):
    line = mline("line_001", 100)
    tr.save_line("p520.001", text="Ա", status="done", geometry=tr.geometry(line))
    assert migrate.after_verify(520, [line], {"line_001": "p520.001"}) == {}
    assert tr.load_page(520)["p520.001"]["text"] == "Ա"


def test_reverify_after_a_reshape_sets_the_test_set_record_aside(dirs):
    tr.save_line("p520.001", text="Ա", status="done", geometry=tr.geometry(mline("line_001", 100)))
    summary = migrate.after_verify(520, [mline("line_001", 110)], {"line_001": "p520.001"})
    assert summary["testset"]["stale"] == {"p520.001": "shape changed"}
    assert tr.load_page(520) == {}
