"""ceiling.score with a typed line the OCR engines have no prediction for (yet)."""

from __future__ import annotations

import json
import os
import signal
import time

import pytest

from dev.line_review import transcribe as tr
from dev.ocr_eval import ceiling, common


def test_score_skips_typed_lines_without_predictions(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(tr, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")
    (tmp_path / "reports").mkdir()
    pred_dir = tmp_path / "data" / "ocr_predictions" / "ceiling"
    pred_dir.mkdir(parents=True)
    # p520.002 was reshaped on verify: its predictions were dropped, then it was retyped
    for engine in ceiling.ENGINES:
        (pred_dir / f"{engine}.json").write_text(json.dumps({"lines": {"p520.001": "Ա"}}))
    (pred_dir / "corr-x.json").write_text(json.dumps({"lines": {"p520.001": "Ա", "p520.002": "Բ"}}))
    tr.save_sample({"seed": "s", "population": {"agree": 10, "disagree": 0},
                    "quotas": {"agree": 2, "disagree": 0},
                    "picks": [{"id": "p520.001", "stratum": "agree", "page": 520},
                              {"id": "p520.002", "stratum": "agree", "page": 520}]}, "ceiling")
    for k, text in (("p520.001", "Ա"), ("p520.002", "Բ")):
        tr.save_line(k, text=text, status="done", task="ceiling")
    ceiling.score()  # used to raise KeyError on p520.002
    report = (tmp_path / "reports" / "phase11_ceiling.md").read_text()
    assert "1 more typed lines wait for the OCR engines to be re-run" in report


def test_a_rewrite_of_a_predictions_file_keeps_its_stale_section(tmp_path, monkeypatch):
    from dev.ocr_eval import common
    monkeypatch.setattr(common, "PREDICTIONS_DIR", tmp_path)
    stale = {"p520~line_002": [{"text": "Բ", "reason": "shape changed", "replaced_by": "p520.002", "at": "t"}]}
    (tmp_path / "corr-x.json").write_text(json.dumps({"lines": {"p520.001": "Ա"}, "stale": stale}))
    common._write("corr-x", {}, {"p520.001": "Ա", "p520.003": "Գ"})
    rec = json.loads((tmp_path / "corr-x.json").read_text())
    assert rec["stale"] == stale and set(rec["lines"]) == {"p520.001", "p520.003"}
    assert not list(tmp_path.glob(".*.tmp"))


def test_the_corrector_only_fills_lines_without_a_correction():
    from dev.ocr_eval.correct import missing_lines, new_lines
    out = {"p520.001": "kept", "p520.002": "kept"}
    assert missing_lines(["p520.001", "p520.002", "p520.003"], out) == ["p520.003"]
    assert new_lines({"p520.001": "new", "p520.003": "new"}, out) == {"p520.003": "new"}


def test_a_rewrite_never_deletes_a_prediction(tmp_path, monkeypatch):
    """A rewrite that drops or replaces lines (--redo, a settings change) sets the old
    readings aside under ``stale``: paid corrector runs must not be lost (PR #9 lost the
    v2/v3/v5 and Gemini 4 corrections of pages 463-492 that way)."""
    monkeypatch.setattr(common, "PREDICTIONS_DIR", tmp_path)
    migrated = [{"text": "Զ", "reason": "shape changed", "replaced_by": "p520.004", "at": "t"}]
    (tmp_path / "corr-x.json").write_text(json.dumps({
        "lines": {"p520.001": "Ա", "p520.002": "Բ", "p520.003": "Գ"},
        "stale": {"p520~line_004": migrated}}))
    common._write("corr-x", {}, {"p520.001": "Ա", "p520.002": "Բբ"})
    rec = json.loads((tmp_path / "corr-x.json").read_text())
    assert rec["lines"] == {"p520.001": "Ա", "p520.002": "Բբ"}
    assert rec["stale"]["p520~line_004"] == migrated
    assert [(e["text"], e["reason"], e["replaced_by"]) for e in rec["stale"]["p520.002"]] == [
        ("Բ", "replaced on rewrite", "p520.002")]
    assert [(e["text"], e["reason"], e["replaced_by"]) for e in rec["stale"]["p520.003"]] == [
        ("Գ", "dropped on rewrite", None)]

    # writing again (e.g. the next incremental save) adds nothing twice
    common._write("corr-x", {}, {"p520.001": "Ա", "p520.002": "Բբ"})
    assert json.loads((tmp_path / "corr-x.json").read_text())["stale"] == rec["stale"]

    # a line predicted again with its old text is the line, not a stale copy of it
    common._write("corr-x", {}, {"p520.001": "Ա", "p520.002": "Բբ", "p520.003": "Գ"})
    rec = json.loads((tmp_path / "corr-x.json").read_text())
    assert "p520.003" not in rec["stale"] and rec["lines"]["p520.003"] == "Գ"


def test_redo_of_a_runner_sets_the_earlier_run_aside(tmp_path, monkeypatch):
    """``run(..., only_missing=False)`` saves partial results as it goes; the earlier
    run's readings survive every save."""
    crops = tmp_path / "crops"
    crops.mkdir()
    for k in ("p520.001", "p520.002"):
        (crops / f"{k}.png").write_bytes(b"")
    monkeypatch.setattr(common, "CROPS_DIR", crops)
    monkeypatch.setattr(common, "PREDICTIONS_DIR", tmp_path)
    (tmp_path / "eng.json").write_text(json.dumps({"settings": {"v": 1},
                                                   "lines": {"p520.001": "old", "p520.002": "Բ"}}))
    common.run("eng", {"v": 2}, lambda png: {"p520.001": "new", "p520.002": "Բ"}[png.stem],
               only_missing=False)
    rec = json.loads((tmp_path / "eng.json").read_text())
    assert rec["lines"] == {"p520.001": "new", "p520.002": "Բ"}
    assert [e["text"] for e in rec["stale"]["p520.001"]] == ["old"] and "p520.002" not in rec["stale"]


def _crops(tmp_path, monkeypatch, keys):
    crops = tmp_path / "crops"
    crops.mkdir()
    for k in keys:
        (crops / f"{k}.png").write_bytes(b"")
    monkeypatch.setattr(common, "CROPS_DIR", crops)
    monkeypatch.setattr(common, "PREDICTIONS_DIR", tmp_path)


def test_a_redo_saved_in_steps_labels_and_records_what_it_replaced(tmp_path, monkeypatch):
    """A redo saves every 10 lines, so lines it hasn't reached are set aside as dropped at
    first; at the end each old reading is "replaced on rewrite" (or gone, if the new text
    is the same reading), with the run and settings that made it."""
    keys = [f"p520.{i:03d}" for i in range(1, 26)]
    _crops(tmp_path, monkeypatch, keys)
    old = {k: f"Ա{i}" for i, k in enumerate(keys)}
    (tmp_path / "eng.json").write_text(json.dumps(
        {"settings": {"v": 1}, "generated_at": "T1", "lines": old}))
    new = dict(old, **{keys[0]: "Բ0", keys[24]: "Բ24", keys[12]: " Ա12 "})  # 2 changed, 1 only spaced
    common.run("eng", {"v": 2}, lambda png: new[png.stem], only_missing=False)
    rec = json.loads((tmp_path / "eng.json").read_text())
    assert rec["lines"] == new
    assert sorted(rec["stale"]) == [keys[0], keys[24]]
    sid = common.settings_id({"v": 1})
    for k in (keys[0], keys[24]):
        [e] = rec["stale"][k]
        assert (e["text"], e["reason"], e["replaced_by"], e["run"], e["settings"]) == (
            old[k], "replaced on rewrite", k, "T1", sid)
    assert rec["stale_settings"] == {sid: {"v": 1}}


def test_only_a_material_change_is_set_aside():
    """Spacing and Unicode composition score the same everywhere; folded punctuation
    doesn't (the test set's raw column), so it counts."""
    old = {"settings": {}, "lines": {"a": "Եբր.", "b": "ա  բ", "c": "ե\u0582", "d": "Եբր."}}
    stale, _ = common.set_aside(old, {"a": "Եբր.", "b": "ա բ", "c": "ե\u0582 ", "d": "Եբր․"})
    assert list(stale) == ["d"]


def test_drain_cancels_unsent_calls_and_keeps_the_ones_in_flight():
    from concurrent.futures import ThreadPoolExecutor
    calls, got = [], []

    def call(i):
        calls.append(i)
        if i == 2:
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(0.3)  # still in flight when the main thread cancels the rest
        return i

    with ThreadPoolExecutor(max_workers=1) as pool:
        interrupted = common.drain([pool.submit(call, i) for i in range(20)],
                                   lambda f: got.append(f.result()))
    assert interrupted and calls == [0, 1, 2] and sorted(got) == [0, 1, 2]


def test_ctrl_c_during_a_run_saves_what_was_predicted(tmp_path, monkeypatch):
    keys = [f"p520.{i:03d}" for i in range(1, 21)]
    _crops(tmp_path, monkeypatch, keys)
    calls = []

    def recognize(png):
        calls.append(png.stem)
        if len(calls) == 3:
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(0.3)
        return "Ա"

    with pytest.raises(SystemExit) as exit_:
        common.run("eng", {}, recognize, workers=1)
    assert exit_.value.code == 130 and len(calls) == 3
    assert json.loads((tmp_path / "eng.json").read_text())["lines"] == {k: "Ա" for k in calls}
