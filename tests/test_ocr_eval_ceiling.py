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
