"""ceiling.score with a typed line the OCR engines have no prediction for (yet)."""

from __future__ import annotations

import json

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
