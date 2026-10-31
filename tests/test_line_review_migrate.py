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
             mline("split_001", 290, ["line_003"]), mline("split_002", 330, ["line_003"])]
    ids = {"line_001": "p520.001", "line_002": "p520.002", "split_001": "p520.003", "split_002": "p520.004"}
    before = {f"p520~{k}": tr.geometry(l) for k, l in before.items()}
    summary = migrate.after_verify(520, after, ids, before)

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
    before = {"p520.001": tr.geometry(line)}
    assert migrate.after_verify(520, [line], {"line_001": "p520.001"}, before) == {}
    assert tr.load_page(520)["p520.001"]["text"] == "Ա"


def test_reverify_after_a_reshape_sets_the_test_set_record_aside(dirs):
    tr.save_line("p520.001", text="Ա", status="done", geometry=tr.geometry(mline("line_001", 100)))
    before = {"p520.001": tr.geometry(mline("line_001", 100))}
    summary = migrate.after_verify(520, [mline("line_001", 110)], {"line_001": "p520.001"}, before)
    assert summary["testset"]["stale"] == {"p520.001": "shape changed"}
    assert tr.load_page(520) == {}


def test_untyped_picks_and_predictions_follow_too(dirs):
    """A page verified with sample picks but nothing typed yet (p463's case)."""
    lines = [mline("line_001", 100), mline("line_002", 200)]
    tr.save_sample({"picks": [{"id": "p463~line_002", "stratum": "agree", "page": 463}]}, "ceiling")
    pred_dir = dirs / "predictions" / "ceiling"
    pred_dir.mkdir(parents=True)
    (pred_dir / "paddle.json").write_text(json.dumps(
        {"lines": {"p463~line_001": "Ա", "p463~line_002": "Բ"}}))
    before = {f"p463~{l['key']}": tr.geometry(l) for l in lines}
    migrate.after_verify(463, lines, {"line_001": "p463.001", "line_002": "p463.002"}, before)
    assert [p["id"] for p in tr.load_sample("ceiling")["picks"]] == ["p463.002"]
    assert json.loads((pred_dir / "paddle.json").read_text())["lines"] == {"p463.001": "Ա", "p463.002": "Բ"}


# --- fixes from the PR #2 review -----------------------------------------------------------


def test_keys_made_by_ops_are_part_of_before(dirs, monkeypatch):
    """A line only the ops made (an add, a split piece) can be sampled before verify."""
    from dev.line_review import storage
    seg = {"page": 520, "lines": [{"id": "line_001", "boundary": mline("x", 100)["boundary"],
                                   "baseline": [[100, 140], [900, 140]], "bbox": [100, 100, 900, 150]}]}
    monkeypatch.setattr(storage, "load_baseline", lambda page: seg)
    added = mline("add_001", 300)
    before = migrate.before_shapes(520, None, [mline("line_001", 100), added])
    assert before["p520~add_001"] == tr.geometry(added)
    tr.save_sample({"picks": [{"id": "p520~add_001", "stratum": "agree", "page": 520}]}, "ceiling")
    typed("p520~add_001", added, "Ա")
    migrate.after_verify(520, [mline("line_001", 100), added],
                         {"line_001": "p520.001", "add_001": "p520.002"}, before)
    assert [p["id"] for p in tr.load_sample("ceiling")["picks"]] == ["p520.002"]
    assert set(tr.load_page(520, "ceiling")) == {"p520.002"}


def test_test_set_predictions_and_crops_follow_their_own_layout(dirs):
    """The test set lives in data/ocr_predictions/*.json and runs/ocr_eval/crops/."""
    (dirs / "predictions").mkdir()
    (dirs / "predictions" / "tess-calfa-n.json").write_text(json.dumps(
        {"lines": {"p520.001": "Ա", "p520.002": "Բ", "p521.001": "Գ"}}))
    crops = dirs / "runs" / "crops"
    crops.mkdir(parents=True)
    for k in ("p520.001", "p520.002"):
        (crops / f"{k}.png").write_bytes(b"png")
    tr.save_sample({"picks": [{"id": "p520.002", "stratum": "vol1-body", "page": 520}]})
    before = {"p520.001": tr.geometry(mline("line_001", 100)), "p520.002": tr.geometry(mline("line_002", 200))}
    migrate.after_verify(520, [mline("line_001", 100), mline("line_002", 210)],  # line_002 reshaped
                         {"line_001": "p520.001", "line_002": "p520.002"}, before)
    preds = json.loads((dirs / "predictions" / "tess-calfa-n.json").read_text())["lines"]
    assert preds == {"p520.001": "Ա", "p521.001": "Գ"}
    assert sorted(p.name for p in crops.iterdir()) == ["p520.001.png"]


def test_a_retired_id_hands_its_pick_to_its_successor(dirs):
    """Re-verify: p520.001 and p520.002 were merged into p520.003."""
    tr.save_sample({"picks": [{"id": "p520.001", "stratum": "agree", "page": 520}]}, "ceiling")
    before = {"p520.001": tr.geometry(mline("line_001", 100)), "p520.002": tr.geometry(mline("line_002", 150))}
    merged = mline("line_001+line_002", 100, ["line_001", "line_002"])
    migrate.after_verify(520, [merged], {"line_001+line_002": "p520.003"}, before,
                         retired={"p520.001": {"superseded_by": ["p520.003"]},
                                  "p520.002": {"superseded_by": ["p520.003"]}})
    sample = tr.load_sample("ceiling")
    assert [(p["id"], p["was"]) for p in sample["picks"]] == [("p520.003", "p520.001")]
    assert "dropped" not in sample


def test_two_picks_merged_into_one_line_keep_one_pick(dirs):
    tr.save_sample({"picks": [{"id": "p520~line_001", "stratum": "agree", "page": 520},
                              {"id": "p520~line_002", "stratum": "agree", "page": 520}]}, "ceiling")
    before = {"p520~line_001": tr.geometry(mline("line_001", 100)),
              "p520~line_002": tr.geometry(mline("line_002", 150))}
    merged = mline("line_001+line_002", 100, ["line_001", "line_002"])
    migrate.after_verify(520, [merged], {"line_001+line_002": "p520.001"}, before)
    sample = tr.load_sample("ceiling")
    assert [p["id"] for p in sample["picks"]] == ["p520.001"]
    assert [p["id"] for p in sample["dropped"]] == ["p520~line_002"]
    assert "already picked" in sample["dropped"][0]["reason"]


def test_effective_line_reads_each_page_file_once_with_a_cache(dirs, monkeypatch):
    for i in (1, 2, 3):
        tr.save_line(f"p520.00{i}", text="Ա", status="done")
    reads = []
    real = tr.load_page
    monkeypatch.setattr(tr, "load_page", lambda *a: (reads.append(a), real(*a))[1])
    cache = {}
    for i in (1, 2, 3):
        assert tr.effective_line(f"p520.00{i}", "ceiling", cache)["text"] == "Ա"
    assert len(reads) == 2  # page 520 for ceiling (empty) and for the test set, once each
