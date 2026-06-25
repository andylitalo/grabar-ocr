"""
Phase A unit checks for the non-character verify path.

Run directly (no framework needed):

    uv run python tests/test_nonchar_verify.py

The functions are also plain ``test_*`` so pytest can collect them. The truth
round-trip uses a temp data dir; the detector-parity check runs against the real
page_0487_auto crops, whose flag set is fixed by the gated detector.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from labeling_ui import pipeline, storage  # noqa: E402

# Flag set fixed by data_prep.line_filter on page_0487_auto (see detect_nonchar gate).
EXPECTED_FLAGGED = {
    "column_1/line_001", "column_1/line_010", "column_1/line_011",
    "column_1/line_045", "column_1/line_046", "column_2/line_001",
}


def test_truth_roundtrips(tmp_path: Path | None = None) -> None:
    """save_nonchar_truth then load_nonchar_truth returns the same verdicts + snapshot."""
    tmp = tmp_path or Path(tempfile.mkdtemp())
    orig = storage.DATA_LINES
    storage.DATA_LINES = tmp
    try:
        page_id = "page_9999_auto"
        verdicts = {
            "column_1/line_001": "empty",
            "column_1/line_002": "character",
        }
        features = {
            "column_1/line_001": {"non_character": True, "glyph_count": 0, "ink_ratio": 2.17},
            "column_1/line_002": {"non_character": False, "glyph_count": 23, "ink_ratio": 0.91},
        }
        meta = pipeline.detector_meta()
        path = storage.save_nonchar_truth(page_id, verdicts, meta, features)
        assert path.exists(), "truth file was not written"

        loaded = storage.load_nonchar_truth(page_id)
        assert loaded is not None
        assert loaded["page_id"] == page_id
        assert loaded["verified_by"] == "human"
        assert loaded["detector"] == meta
        l1 = loaded["lines"]["column_1/line_001"]
        assert l1["truth"] == "empty"
        assert l1["detector_nonchar"] is True
        assert l1["glyph_count"] == 0
        l2 = loaded["lines"]["column_1/line_002"]
        assert l2["truth"] == "character"
        assert l2["detector_nonchar"] is False

        # File is valid UTF-8 JSON on disk.
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["lines"] == loaded["lines"]
        assert storage.nonchar_verified(page_id) is True
        print("test_truth_roundtrips: OK")
    finally:
        storage.DATA_LINES = orig


def test_detector_parity_page_0487() -> None:
    """line_nonchar_verdicts reproduces the known flag set and keeps line_009 char."""
    page_dir = storage.DATA_LINES / "page_0487_auto"
    if not page_dir.is_dir():
        print("test_detector_parity_page_0487: SKIP (no page_0487_auto crops)")
        return
    v = pipeline.line_nonchar_verdicts("page_0487_auto")
    flagged = {k for k, d in v.items() if d["non_character"]}
    assert flagged == EXPECTED_FLAGGED, f"flag set drifted: {sorted(flagged)}"
    assert v["column_1/line_009"]["non_character"] is False, "real wrapped word wrongly flagged"
    print("test_detector_parity_page_0487: OK")


if __name__ == "__main__":
    test_truth_roundtrips()
    test_detector_parity_page_0487()
    print("\nAll Phase A unit checks passed.")
