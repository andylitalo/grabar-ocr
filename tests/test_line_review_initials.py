"""
Tests for initial-capital finding (dev.line_review.initials): automatic proposals on a
fresh review, and the line the Initial tool's drawn box joins.

Synthetic pages: white image, text lines drawn as rows of small ink blocks under a box,
capitals as tall ink blocks at a line's start. Line height is 50 px.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from dev.line_review import initials
from dev.line_review import materialize as mz
from dev.line_review import storage

W, H = 2200, 1200


def page():
    return np.full((H, W), 255, np.uint8)


def ink(img, x1, y1, x2, y2):
    img[y1:y2, x1:x2] = 0


def text_line(img, key, x1, y1, x2, y2=None):
    """A line box with letter-sized ink inside it."""
    y2 = y2 or y1 + 50
    for x in range(x1 + 5, x2 - 30, 40):
        ink(img, x, y1 + 12, x + 25, y2 - 10)
    return {"key": key, "bbox": [x1, y1, x2, y2],
            "boundary": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]}


def two_lines():
    img = page()
    lines = [text_line(img, "line_001", 300, 200, 1000), text_line(img, "line_002", 300, 260, 1000)]
    return img, lines


def test_a_small_initial_rising_above_its_line():
    img, lines = two_lines()
    ink(img, 240, 170, 290, 250)  # 80 tall, top 30 px above the line
    [p] = initials.detect(img, lines)
    assert p["line"] == "line_001" and p["absorbs"] == []
    assert p["box"] == [237, 167, 293, 253]


def test_a_drop_cap_joins_the_upper_line():
    img, lines = two_lines()
    ink(img, 200, 200, 270, 310)  # spans both lines, left of them
    [p] = initials.detect(img, lines)
    assert p["line"] == "line_001"


def test_a_capital_in_two_strokes_is_one_initial():
    img, lines = two_lines()
    ink(img, 220, 170, 245, 250)  # Ա: two strokes 10 px apart
    ink(img, 255, 170, 285, 250)
    [p] = initials.detect(img, lines)
    assert p["box"][0] == 217 and p["box"][2] == 288


def test_ordinary_text_is_not_an_initial():
    img, lines = two_lines()
    assert initials.detect(img, lines) == []


def test_a_capital_the_line_already_holds_is_left_alone():
    img = page()
    lines = [text_line(img, "line_001", 230, 165, 1000, 255)]
    ink(img, 240, 170, 290, 250)
    assert initials.detect(img, lines) == []


def test_column_rules_are_not_initials():
    img, lines = two_lines()
    ink(img, 270, 100, 280, 600)  # thin and long
    assert initials.detect(img, lines) == []


def test_a_frame_rule_segment_is_not_an_initial():
    # p.606: a stretch of the page frame beside the first line, 24 x 250 px.
    img, lines = two_lines()
    ink(img, 266, 150, 290, 400)
    assert initials.detect(img, lines) == []


def test_paddles_box_over_the_capital_alone_is_absorbed():
    img, lines = two_lines()
    ink(img, 240, 170, 290, 250)
    lines.append({"key": "line_009", "bbox": [238, 168, 292, 210],
                  "boundary": [[238, 168], [292, 168], [292, 210], [238, 210]]})
    [p] = initials.detect(img, lines)
    assert p["line"] == "line_001" and p["absorbs"] == ["line_009"]
    ops = initials.auto_ops(img, lines)
    assert [o["op"] for o in ops] == ["delete", "initial"]
    mz.materialize_page(lines_for_mz(lines), ops)  # applies cleanly


def lines_for_mz(lines):
    return [{**l, "baseline": [[l["bbox"][0], l["bbox"][3]], [l["bbox"][2], l["bbox"][3]]],
             "baseline_source": "synthetic", "source": "hyocr-paddle",
             "derived_from": [l["key"]], "lineage": []} for l in lines]


def test_the_line_comes_from_the_capitals_own_column():
    # p.460: the left-column line starts 1 px left of the capital and a right-column
    # line sits a little higher. The old UI rule took the right column.
    img = page()
    lines = [text_line(img, "left", 318, 231, 1000), text_line(img, "right", 1100, 221, 1900)]
    ink(img, 319, 216, 373, 290)
    [p] = initials.detect(img, lines)
    assert p["line"] == "left"
    assert initials.target_for_box(lines, [319, 216, 373, 290])["line"] == "left"


def test_a_drawn_box_over_paddles_capital_box_absorbs_it():
    img, lines = two_lines()
    lines.append({"key": "line_009", "bbox": [238, 168, 292, 210],
                  "boundary": [[238, 168], [292, 168], [292, 210], [238, 210]]})
    assert initials.target_for_box(lines, [236, 166, 294, 252]) == {
        "line": "line_001", "absorbs": ["line_009"]}


# --- fresh reviews ---------------------------------------------------------------

@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    from PIL import Image
    img, lines = two_lines()
    ink(img, 240, 170, 290, 250)
    ink(img, 1040, 60, 1060, 140)   # the page number's bracket, capital-sized
    ink(img, 1070, 70, 1180, 130)
    seg = {"page": 463, "width": W, "height": H, "lines": [
        {"id": l["key"], "boundary": l["boundary"], "bbox": l["bbox"], "source": "hyocr-paddle",
         "text": "", "baseline": [[l["bbox"][0], l["bbox"][3]], [l["bbox"][2], l["bbox"][3]]]}
        for l in lines] + [
        {"id": "line_090", "boundary": [[1035, 55], [1190, 55], [1190, 145], [1035, 145]],
         "bbox": [1035, 55, 1190, 145], "source": "hyocr-paddle", "text": "-( 459)",
         "baseline": [[1035, 135], [1190, 135]]}]}
    (tmp_path / "baseline" / "page_463").mkdir(parents=True)
    (tmp_path / "baseline" / "page_463" / "segmentation.json").write_text(json.dumps(seg))
    (tmp_path / "renders" / "page_463").mkdir(parents=True)
    Image.fromarray(img).save(tmp_path / "renders" / "page_463" / "render.png")
    monkeypatch.setattr(storage, "BASELINE_DIR", tmp_path / "baseline")
    monkeypatch.setattr(storage, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "REVIEWS_DIR", tmp_path / "reviews")
    return tmp_path


def test_a_fresh_review_starts_with_page_number_and_initials(tmp_store):
    ops = storage.load_review(463)["ops"]
    assert ops == [
        {"op": "page_number", "line": "line_090", "value": "459", "auto": True},
        {"op": "initial", "box": [237, 167, 293, 253], "line": "line_001", "auto": True}]


# --- the reviewer's own initials (pp.453-463) ---------------------------------------

@pytest.mark.skipif(not storage.RENDER_DIR.exists(), reason="page renders not present")
def test_finds_every_initial_the_reviewer_marked():
    def overlaps(a, b):
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix * iy > 0.5 * (a[2] - a[0]) * (a[3] - a[1])

    missed = []
    for page in range(453, 464):
        path = storage.review_path(page)
        if not path.exists():
            continue
        marked = [o["box"] for o in json.loads(path.read_text())["ops"] if o["op"] == "initial"]
        lines = mz.baseline_lines(storage.load_baseline(page))
        found = [p["box"] for p in initials.detect(storage.page_image(page), lines)]
        missed += [(page, b) for b in marked if not any(overlaps(f, b) for f in found)]
    assert missed == []



# --- lines Paddle boxed twice ---------------------------------------------------------

TWINS = [{"key": "a", "bbox": [1158, 2340, 1972, 2389]},
         {"key": "b", "bbox": [1160, 2394, 1970, 2443]},
         {"key": "c", "bbox": [1159, 2341, 1973, 2391]},   # a's twin, slightly larger
         {"key": "d", "bbox": [1160, 2440, 1970, 2540]}]   # b's neighbour, touching it


def test_the_smaller_copy_of_a_line_boxed_twice_is_dropped():
    from dev.line_review import duplicates
    assert duplicates.pairs(TWINS) == [("c", "a")]
    assert [l["key"] for l in duplicates.dedupe(TWINS)] == ["b", "c", "d"]


def test_a_pair_the_reviewer_handled_is_left_alone():
    from dev.line_review import duplicates
    keys = lambda ops: [l["key"] for l in duplicates.dedupe(TWINS, ops)]
    assert keys([{"op": "delete", "line": "a"}]) == ["a", "b", "c", "d"]   # p.473
    assert keys([{"op": "delete", "line": "c"}]) == ["a", "b", "c", "d"]
    assert keys([{"op": "initial", "line": "c", "box": [0, 0, 1, 1]}]) == ["b", "c", "d"]


def test_the_materializer_drops_copies_before_the_ops():
    lines = lines_for_mz([{**l, "boundary": [[l["bbox"][0], l["bbox"][1]], [l["bbox"][2], l["bbox"][1]],
                                              [l["bbox"][2], l["bbox"][3]], [l["bbox"][0], l["bbox"][3]]]}
                          for l in TWINS])
    assert sorted(l["key"] for l in mz.materialize_page(lines, [])["lines"]) == ["b", "c", "d"]


def _rows(n=5):
    return [{"key": f"r{i}", "bbox": [1000, 100 + 60 * i, 1800, 150 + 60 * i]} for i in range(n)]


def test_a_speck_inside_a_line_is_dropped():
    # p.485: "է", 20 x 12 px inside line_054. Its IoU with the line is ~0.01.
    from dev.line_review import duplicates
    lines = _rows() + [{"key": "speck", "bbox": [1170, 138, 1190, 150]}]
    assert [l["key"] for l in duplicates.dedupe(lines)] == [f"r{i}" for i in range(5)]


def test_a_box_smaller_than_a_character_is_dropped_but_thin_lines_and_letters_stay():
    from dev.line_review import duplicates
    lines = _rows() + [{"key": "speck", "bbox": [500, 500, 530, 525]},        # p.560
                       {"key": "thin", "bbox": [500, 600, 900, 620]},         # p.490
                       {"key": "letter", "bbox": [500, 700, 536, 745]}]       # p.641 cell
    assert duplicates.specks(lines) == ["speck"]
    assert "speck" in {l["key"] for l in duplicates.dedupe(lines, [{"op": "reshape", "line": "speck"}])}


def test_an_initials_tall_box_over_the_next_line_is_not_a_copy():
    # p.492: the drop cap made line 31's box reach down over line 32; the outlines don't meet.
    from dev.line_review import duplicates
    upper = {"key": "u", "bbox": [340, 2023, 1130, 2147],
             "boundary": [[340, 2023], [1130, 2023], [1130, 2110], [447, 2110], [447, 2147], [340, 2147]]}
    lower = {"key": "l", "bbox": [431, 2115, 1131, 2171],
             "boundary": [[447, 2115], [1131, 2115], [1131, 2171], [447, 2171]]}
    assert duplicates.pairs([upper, lower]) == [("u", "l")]
    assert duplicates.outline_pairs([upper, lower]) == []
