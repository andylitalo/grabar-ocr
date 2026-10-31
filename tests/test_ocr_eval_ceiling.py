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
