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

    for engine in ("tess-calfa-n", "corr-gemini"):
        # A corrector is treated like any engine: its correction of an unchanged line is
        # kept (the scores don't move); a changed line's is set aside, never deleted.
        rec = json.loads((pred_dir / f"{engine}.json").read_text())
        assert rec["lines"] == {"p520.001": "p520~line_001", "p521~line_001": "p521~line_001"}
        assert {k: [e["reason"] for e in v] for k, v in rec["stale"].items()} == {
            "p520~line_002": ["shape changed"], "p520~line_003": ["line split or merged"],
            "p520~line_004": ["line removed"]}
        assert rec["stale"]["p520~line_003"][0] == {**rec["stale"]["p520~line_003"][0],
                                                    "text": "p520~line_003", "replaced_by": "p520.003"}


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


def seg_520(monkeypatch):
    from dev.line_review import storage
    seg = {"page": 520, "lines": [{"id": "line_001", "boundary": mline("x", 100)["boundary"],
                                   "baseline": [[100, 140], [900, 140]], "bbox": [100, 100, 900, 150]}]}
    monkeypatch.setattr(storage, "load_baseline", lambda page: seg)


def test_a_line_made_by_ops_moves_but_its_ocr_is_redone(dirs, monkeypatch):
    """An added line's earlier shape isn't known: its pick and (same-shape) record move,
    its predictions and crop are dropped, since they may be of a shape the review changed."""
    seg_520(monkeypatch)
    added = mline("add_001", 300)
    assert "p520~add_001" not in migrate.before_shapes(520)
    tr.save_sample({"picks": [{"id": "p520~add_001", "stratum": "agree", "page": 520}]}, "ceiling")
    typed("p520~add_001", added, "Ա")
    pred_dir = dirs / "predictions" / "ceiling"
    pred_dir.mkdir(parents=True)
    (pred_dir / "paddle.json").write_text(json.dumps({"lines": {"p520~add_001": "old shape's OCR"}}))
    crops = dirs / "runs" / "ceiling_crops"
    crops.mkdir(parents=True)
    (crops / "p520~add_001.png").write_bytes(b"png")
    migrate.after_verify(520, [mline("line_001", 100), added],
                         {"line_001": "p520.001", "add_001": "p520.002"}, migrate.before_shapes(520))
    assert [p["id"] for p in tr.load_sample("ceiling")["picks"]] == ["p520.002"]
    assert set(tr.load_page(520, "ceiling")) == {"p520.002"}
    assert json.loads((pred_dir / "paddle.json").read_text())["lines"] == {}
    assert list(crops.iterdir()) == []


def test_a_line_the_ops_made_and_removed_is_not_left_behind(dirs, monkeypatch):
    """add_001 was typed and picked, then deleted before the verify."""
    seg_520(monkeypatch)
    typed("p520~add_001", mline("add_001", 300), "Ա")
    tr.save_sample({"picks": [{"id": "p520~add_001", "stratum": "agree", "page": 520}]}, "ceiling")
    summary = migrate.after_verify(520, [mline("line_001", 100)], {"line_001": "p520.001"},
                                   migrate.before_shapes(520))
    assert summary["ceiling"]["stale"] == {"p520~add_001": "line removed"}
    assert tr.load_page(520, "ceiling") == {}
    sample = tr.load_sample("ceiling")
    assert sample["picks"] == [] and [p["id"] for p in sample["dropped"]] == ["p520~add_001"]


def test_a_retired_id_with_no_earlier_shape_is_followed_too(dirs):
    """repair has no previous verified output: a test-set record on a retired id still
    goes stale instead of being skipped."""
    tr.save_line("p520.001", text="Ա", status="done", geometry=tr.geometry(mline("line_001", 100)))
    merged = mline("line_001+line_002", 120, ["line_001", "line_002"])
    summary = migrate.after_verify(520, [merged], {"line_001+line_002": "p520.003"}, {},
                                   retired={"p520.001": {"superseded_by": ["p520.003"]}})
    assert summary["testset"]["stale"] == {"p520.001": "line split or merged"}


def test_a_retry_does_not_set_a_record_aside_twice(dirs, monkeypatch):
    lines = [mline("line_001", 100), mline("line_002", 200)]
    before = {f"p520~{l['key']}": tr.geometry(l) for l in lines}
    typed("p520~line_001", lines[0], "Ա")
    typed("p520~line_002", lines[1], "Բ")
    after = [mline("line_001", 105), mline("line_002", 205)]  # both reshaped
    ids = {"line_001": "p520.001", "line_002": "p520.002"}
    real = tr._write_page
    monkeypatch.setattr(tr, "_write_page", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    try:
        migrate.after_verify(520, after, ids, before)
    except OSError:
        pass
    monkeypatch.setattr(tr, "_write_page", real)
    migrate.after_verify(520, after, ids, before)
    stale = json.loads((dirs / "transcriptions" / "ceiling" / "stale" / "page_520.json").read_text())
    assert [s["id"] for s in stale] == ["p520~line_001", "p520~line_002"]
    assert tr.load_page(520, "ceiling") == {}


def test_a_crop_already_under_its_new_id_replaces_the_old_one(dirs):
    tr.save_sample({"picks": []}, "ceiling")
    crops = dirs / "runs" / "ceiling_crops"
    crops.mkdir(parents=True)
    for k in ("p520~line_001", "p520.001"):
        (crops / f"{k}.png").write_bytes(b"png")
    line = mline("line_001", 100)
    migrate.after_verify(520, [line], {"line_001": "p520.001"}, {"p520~line_001": tr.geometry(line)})
    assert [p.name for p in crops.iterdir()] == ["p520.001.png"]


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


def test_a_rerun_of_repair_keeps_the_stale_predictions_once(dirs):
    tr.save_sample({"picks": []}, "ceiling")
    pred_dir = dirs / "predictions" / "ceiling"
    pred_dir.mkdir(parents=True)
    (pred_dir / "corr-x.json").write_text(json.dumps({"lines": {"p520~line_001": "Ա"}}))
    before = {"p520~line_001": tr.geometry(mline("line_001", 100))}
    for _ in range(2):
        migrate.after_verify(520, [mline("line_001", 110)], {"line_001": "p520.001"}, before)
    rec = json.loads((pred_dir / "corr-x.json").read_text())
    assert rec["lines"] == {} and len(rec["stale"]["p520~line_001"]) == 1
