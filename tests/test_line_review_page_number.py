"""
Tests for automatic page-number marking (dev.line_review.page_number).

The printed page number (the running header ``-( 459 )-``) is the topmost line on a
numbered page, centred, small, above the double rule. ``detect`` finds that line in a
paddle-filled baseline; a fresh review starts with a ``page_number`` op on it.
"""

from __future__ import annotations

import json

import pytest

from dev.line_review import page_number as pn
from dev.line_review import storage


def line(key, x1, y1, x2, y2, source="hyocr-paddle", text=""):
    return {"id": key, "boundary": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
            "bbox": [x1, y1, x2, y2], "source": source, "text": text}


def seg(*lines, width=2192):
    return {"page": 463, "width": width, "height": 3100, "lines": list(lines)}


BODY = [line("line_001", 100, 330, 1050, 380, text="Ի սուրբ"),
        line("line_002", 1150, 330, 2100, 380, text="Աստուած")]


def test_finds_the_paddle_running_header():
    s = seg(*BODY, line("line_090", 940, 170, 1260, 265, text="-( 459)"))
    assert pn.detect(s) == "line_090"


def test_finds_a_kraken_fill_over_the_digits():
    # Paddle missed the number; the kraken fill covers only the digits (p.491).
    s = seg(*BODY, line("line_047", 962, 168, 1056, 239, source="kraken-fill"))
    assert pn.detect(s) == "line_047"


def test_ignores_a_section_heading_at_the_top():
    # A first page of a section opens with a wide title, not a number (p.457).
    s = seg(*BODY, line("line_000", 300, 101, 1871, 202, text="ԿԱՆՈՆ ԱՍՏՈՒԱԾԱՅԱՅՏՆՈ"))
    assert pn.detect(s) is None


def test_ignores_a_narrow_title_word():
    # "ԿԱՆՈՆ" alone is centred and short, but wider and lower than a number (p.483).
    s = seg(*BODY, line("line_000", 900, 300, 1313, 397, text="ԿԱՆՈՆ"))
    assert pn.detect(s) is None


def test_paddle_text_without_digits_or_brackets_is_not_a_number():
    s = seg(*BODY, line("line_090", 940, 170, 1260, 265, text="Տէր"))
    assert pn.detect(s) is None


def test_off_centre_box_is_not_a_number():
    s = seg(*BODY, line("line_090", 1500, 170, 1820, 265, text="-( 459)"))
    assert pn.detect(s) is None


def test_only_the_topmost_line_is_considered():
    s = seg(line("line_000", 100, 120, 2100, 200, text="ԳԼՈՒԽ"),
            line("line_090", 940, 210, 1260, 300, text="-( 459)"), *BODY)
    assert pn.detect(s) is None


def test_empty_page():
    assert pn.detect(seg()) is None


def test_auto_op_uses_the_expected_value_not_paddles_reading():
    s = seg(*BODY, line("line_090", 940, 170, 1260, 265, text="-( 458)"))  # misread
    assert pn.auto_ops(s, "459") == [
        {"op": "page_number", "line": "line_090", "value": "459", "auto": True}]
    assert pn.auto_ops(seg(*BODY), "459") == []


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    base = tmp_path / "baseline"
    (base / "page_463").mkdir(parents=True)
    s = seg(*BODY, line("line_090", 940, 170, 1260, 265, text="-( 459)"))
    for l in s["lines"]:
        y = l["bbox"][3] - 10
        l["baseline"] = [[l["bbox"][0], y], [l["bbox"][2], y]]
    (base / "page_463" / "segmentation.json").write_text(json.dumps(s))
    monkeypatch.setattr(storage, "BASELINE_DIR", base)
    monkeypatch.setattr(storage, "REVIEWS_DIR", tmp_path / "reviews")
    monkeypatch.setattr(storage, "RENDER_DIR", tmp_path / "renders")  # no image: no initials
    return tmp_path


def test_a_fresh_review_starts_with_the_page_number_marked(tmp_store):
    review = storage.load_review(463)
    assert review["status"] == "unreviewed"
    assert review["ops"] == [
        {"op": "page_number", "line": "line_090", "value": "459", "auto": True}]
    assert [l["key"] for l in storage.materialized(463, review)] == ["line_001", "line_002"]


def test_a_saved_review_is_not_reseeded(tmp_store):
    storage.save_ops(463, [], [])  # the reviewer removed the auto mark
    assert storage.load_review(463)["ops"] == []


# --- the real book --------------------------------------------------------------

# Pages in 453-643 whose top has no printed number: title pages, section openings
# (a heading or a hymn's first line on top), and blank pages.
UNNUMBERED = {453, 454, 455, 456, 457, 481, 482, 483, 495, 496, 497, 501, 502, 503,
              514, 515, 521, 522, 523, 529, 530, 531, 552, 553, 554, 555, 557}


@pytest.mark.skipif(not storage.BASELINE_DIR.exists(), reason="paddle-filled not present")
def test_book_wide_detection_matches_the_survey():
    marked = {p for p in storage.list_pages() if pn.detect(storage.load_baseline(p))}
    assert marked == set(storage.list_pages()) - UNNUMBERED
