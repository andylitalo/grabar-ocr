"""
Tests for automatic unclipping (dev.line_review.unclip).

Paddle's boxes often run along the tips of descenders (ր ը զ ց ղ դ) or under the top of a
capital, so the crop loses a few pixels of the letter. A fresh review starts with
``reshape`` ops (``"auto": true``) that push each box out locally over the letters it cuts,
without taking in another line's letters.

Synthetic pages: white images with black rectangles as letters, lines as boxes.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from shapely.geometry import Polygon
from shapely.geometry import box as shapely_box

from dev.line_review import materialize as mz
from dev.line_review import storage, unclip

H, W = 400, 600


def rect(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def line(key, x1, y1, x2, y2):
    return {"key": key, "boundary": rect(x1, y1, x2, y2), "bbox": [x1, y1, x2, y2]}


def page(*letters):
    """A white page with black rectangles (x1, y1, x2, y2), ends exclusive."""
    img = np.full((H, W), 255, np.uint8)
    for x1, y1, x2, y2 in letters:
        img[y1:y2, x1:x2] = 0
    return img


def by_line(ops):
    assert all(op["op"] == "reshape" and op["auto"] is True for op in ops)
    return {op["line"]: Polygon(op["boundary"]) for op in ops}


def covers(poly, x1, y1, x2, y2):
    """Every pixel of the letter (x1..x2-1, y1..y2-1) lies inside the polygon."""
    return poly.buffer(1e-6).contains(shapely_box(x1, y1, x2 - 1, y2 - 1))


# A body line: letters 40-70 px tall in a box from y=100 to y=160.
BODY = [(50, 110, 80, 150), (100, 110, 130, 150), (150, 110, 180, 150)]


def test_nothing_cut_means_no_ops():
    assert unclip.auto_ops([line("line_001", 40, 100, 300, 160)], page(*BODY)) == []


def test_a_descender_below_the_box_is_taken_in_with_a_margin():
    desc = (200, 110, 215, 168)          # 8 px below the box's bottom edge (160)
    ops = unclip.auto_ops([line("line_001", 40, 100, 300, 160)], page(*BODY, desc))
    poly = by_line(ops)["line_001"]
    assert covers(poly, *desc)
    assert poly.bounds[3] >= 168 - 1 + unclip.MARGIN
    # only locally: the bottom edge away from the descender is where it was
    assert not poly.contains(shapely_box(60, 161, 61, 162))


def test_a_tip_touching_the_edge_counts_as_cut():
    # The tip ends exactly on the edge: no margin left, so it's extended too.
    tip = (200, 110, 215, 161)
    poly = by_line(unclip.auto_ops([line("line_001", 40, 100, 300, 160)], page(*BODY, tip)))["line_001"]
    assert poly.bounds[3] >= 160 + unclip.MARGIN


def test_a_tall_capital_mostly_above_the_box_is_taken_in():
    # Only its foot is in the box (~20%), but no other line touches it.
    cap = (40, 60, 70, 150)
    poly = by_line(unclip.auto_ops([line("line_001", 35, 130, 300, 190)], page(*BODY, cap)))["line_001"]
    assert covers(poly, *cap)


def test_a_drop_cap_beside_two_lines_is_left_to_review():
    # A two-line drop cap, mostly outside every box: attaching it is the reviewer's
    # `initial` (p.460). Taking it into one line had raised that box above the line
    # before it and changed the reading order.
    upper = line("line_001", 130, 100, 400, 160)
    lower = line("line_002", 100, 175, 400, 235)
    cap = (60, 110, 125, 220)           # 1.8 line heights; ~16% of it inside line_002
    letters = [(140, 110, 170, 150), (140, 185, 170, 225)]
    assert unclip.auto_ops([upper, lower], page(*letters, cap)) == []


# --- specks: small blobs in the gap between lines are not taken in --------------------
# BODY's letters span y 110-150: that's the line's text band.

def test_a_speck_below_the_text_is_not_taken_in():
    speck = (200, 157, 208, 165)        # under the text, 20 px from the nearest letter
    assert unclip.auto_ops([line("line_001", 40, 100, 300, 160)], page(*BODY, speck)) == []


def test_a_speck_nearer_another_lines_letters_is_not_taken_in():
    # Above the lower line's text, but as close to the upper line's descender as to the
    # lower line's own letters (p.479).
    upper = line("line_001", 40, 100, 300, 160)
    lower = line("line_002", 40, 172, 300, 232)
    lower_letters = [(60, 182, 90, 222), (110, 182, 140, 222), (240, 182, 270, 222)]
    desc = (200, 110, 215, 157)         # the upper line's letter, inside its box
    speck = (203, 166, 209, 174)        # 9 px under it; 8+ px from the lower line's letters
    ops = unclip.auto_ops([upper, lower], page(*BODY, desc, *lower_letters, speck))
    assert "line_002" not in by_line(ops)


def test_a_descender_is_still_taken_in():
    # A descender belongs to its letter's blob, so it is never a speck, however low.
    desc = (200, 110, 215, 168)
    poly = by_line(unclip.auto_ops([line("line_001", 40, 100, 300, 160)], page(*BODY, desc)))["line_001"]
    assert covers(poly, *desc)


@pytest.mark.parametrize("mark", [
    (183, 96, 188, 106),    # apostrophe ՚ just above a letter, 4 px from it
    (205, 97, 213, 105),    # accent ՛ above the text, 25 px from the nearest letter
])
def test_marks_above_the_text_are_still_taken_in(mark):
    # Above the text, a small blob can be an accent, ՚ or ՟: taken in even far from a letter
    # (a speck above the text can't be told from these, so it is kept too).
    poly = by_line(unclip.auto_ops([line("line_001", 40, 100, 300, 160)], page(*BODY, mark)))["line_001"]
    assert covers(poly, *mark)


def test_a_period_on_the_baseline_is_still_taken_in():
    # The box sits on the baseline; a period there is in the text band, not a speck.
    period = (200, 143, 207, 152)
    poly = by_line(unclip.auto_ops([line("line_001", 40, 100, 300, 150)], page(*BODY, period)))["line_001"]
    assert covers(poly, *period)


def test_a_box_with_a_narrow_neck_still_works():
    # A hand-reshaped box (p.453 onwards) can have a neck thinner than 2 * INSET: shrinking
    # it for the cut test splits it in two, and a drop cap's notch can be that thin.
    neck = [[40, 100], [300, 100], [300, 160], [180, 160], [180, 157], [176, 157],
            [176, 160], [40, 160]]
    lines = [{"key": "line_001", "boundary": neck, "bbox": [40, 100, 300, 160]},
             line("line_002", 40, 300, 300, 360)]
    thin = [{"key": "line_001", "boundary": rect(40, 100, 300, 102.5), "bbox": [40, 100, 300, 102.5]}]
    desc = (200, 110, 215, 168)
    poly = by_line(unclip.auto_ops(lines, page(*BODY, desc)))["line_001"]
    assert covers(poly, *desc)
    unclip.auto_ops(thin, page(*BODY))   # shrinks to nothing: no crash


# --- carving: a tip inside the next line's box is cut out of that box ----------------

UPPER = line("line_001", 40, 100, 300, 160)
LOWER = line("line_002", 40, 172, 300, 232)
LOWER_LETTERS = [(60, 182, 90, 222), (110, 182, 140, 222), (240, 182, 270, 222)]


def final(lines, ops):
    """Each line's polygon after the ops."""
    polys = by_line(ops)
    return {l["key"]: polys.get(l["key"], Polygon(l["boundary"])) for l in lines}


def test_a_descender_inside_the_next_box_is_carved_out_of_it():
    desc = (200, 110, 215, 180)         # 8 px into the lower box, away from its letters
    ops = unclip.auto_ops([UPPER, LOWER], page(*BODY, desc, *LOWER_LETTERS))
    polys = final([UPPER, LOWER], ops)
    assert covers(polys["line_001"], *desc)
    assert polys["line_001"].intersection(polys["line_002"]).area < unclip.SLIVER   # no overlap
    for letter in LOWER_LETTERS:
        assert covers(polys["line_002"], *letter)
    x1, y1, x2, y2 = desc                # the tip's pixels, plus the margin, are out of it
    assert polys["line_002"].distance(shapely_box(x1, y1, x2 - 1, y2 - 1)) >= unclip.MARGIN - 0.5


def test_no_carving_next_to_the_other_lines_letter():
    # The tip comes within 2 px of the lower line's own letter: carving would cut into the
    # space around that letter, so neither box changes there and the tip stays cut.
    desc = (200, 110, 215, 184)
    near = (217, 182, 247, 222)         # 2 px to the right of the tip
    ops = unclip.auto_ops([UPPER, LOWER], page(*BODY, desc, near, *LOWER_LETTERS))
    polys = final([UPPER, LOWER], ops)
    assert "line_002" not in by_line(ops)
    assert polys["line_001"].intersection(polys["line_002"]).area < unclip.SLIVER


def test_carving_never_splits_the_other_box():
    # A thin lower box: cutting the tip out would split it in two, so it isn't carved.
    thin = line("line_002", 40, 172, 300, 178)
    desc = (200, 110, 215, 182)
    ops = unclip.auto_ops([UPPER, thin], page(*BODY, desc))
    polys = final([UPPER, thin], ops)
    assert "line_002" not in by_line(ops)
    assert polys["line_001"].intersection(polys["line_002"]).area < unclip.SLIVER


def test_keeps_clear_of_a_neighbours_overhanging_letter():
    # The lower line's capital sticks up out of its own box into the gap, right under
    # the upper line's descender: the descender is taken in, the capital is not.
    upper = line("line_001", 40, 100, 300, 160)
    lower = line("line_002", 40, 190, 300, 250)
    desc = (200, 110, 215, 166)
    cap = (195, 172, 225, 240)          # top 18 px outside its own box
    ops = unclip.auto_ops([upper, lower], page(*BODY, desc, cap, (60, 200, 90, 240)))
    polys = by_line(ops)
    assert covers(polys["line_001"], *desc)
    assert polys["line_001"].distance(shapely_box(*cap)) >= unclip.GUARD - 0.5
    assert covers(polys["line_002"], *cap)   # and the capital goes to its own line


def test_a_letter_split_between_two_boxes_is_left_alone():
    # Half in each box: neither line owns it, so neither is extended over it.
    upper = line("line_001", 40, 100, 300, 160)
    lower = line("line_002", 40, 170, 300, 230)
    shared = (200, 140, 215, 190)
    ops = unclip.auto_ops([upper, lower], page(*BODY, shared, (60, 180, 90, 220)))
    assert ops == []


def test_a_rule_taller_than_letters_is_ignored():
    rule = (290, 20, 296, 380)          # a vertical rule crossing the box
    assert unclip.auto_ops([line("line_001", 40, 100, 300, 160)], page(*BODY, rule)) == []


def test_specks_are_ignored():
    speck = (200, 158, 203, 163)        # 9 px of dust on the edge
    assert unclip.auto_ops([line("line_001", 40, 100, 300, 160)], page(*BODY, speck)) == []


def test_ops_materialize_onto_the_baseline():
    lines = [line("line_001", 40, 100, 300, 160)]
    desc = (200, 110, 215, 168)
    ops = unclip.auto_ops(lines, page(*BODY, desc))
    base = [{**l, "id": l["key"], "source": "hyocr-paddle",
             "baseline": [[40, 145], [300, 145]]} for l in lines]
    out = mz.materialize_page(mz.baseline_lines({"lines": base}), ops)["lines"]
    assert covers(Polygon(out[0]["boundary"]), *desc)


# --- storage: a fresh review starts with the ops -----------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    base = tmp_path / "baseline"
    (base / "page_500").mkdir(parents=True)
    seg = {"page": 500, "tool": "paddle-filled", "width": W, "height": H, "lines": [
        {"id": "line_001", "boundary": rect(40, 100, 300, 160), "bbox": [40, 100, 300, 160],
         "baseline": [[40, 145], [300, 145]], "source": "hyocr-paddle"}]}
    (base / "page_500" / "segmentation.json").write_text(json.dumps(seg))
    monkeypatch.setattr(storage, "BASELINE_DIR", base)
    monkeypatch.setattr(storage, "REVIEWS_DIR", tmp_path / "reviews")
    monkeypatch.setattr(storage, "RENDER_DIR", tmp_path / "renders")
    return tmp_path


def write_render(root, img):
    import cv2
    (root / "renders" / "page_500").mkdir(parents=True)
    cv2.imwrite(str(root / "renders" / "page_500" / "render.png"), img)


def test_a_fresh_review_starts_with_the_unclip_ops(store):
    write_render(store, page(*BODY, (200, 110, 215, 168)))
    ops = storage.load_review(500)["ops"]
    assert [(o["op"], o["line"], o.get("auto")) for o in ops] == [("reshape", "line_001", True)]


def test_without_a_render_there_are_no_unclip_ops(store):
    assert storage.load_review(500)["ops"] == []


def test_a_saved_review_is_not_reseeded(store):
    write_render(store, page(*BODY, (200, 110, 215, 168)))
    storage.save_ops(500, [], [])   # the reviewer removed the auto edits
    assert storage.load_review(500)["ops"] == []


def test_review_files_write_one_op_per_line(store):
    write_render(store, page(*BODY, (200, 110, 215, 168)))
    review = storage.load_review(500)
    storage.save_ops(500, review["ops"], [])
    text = storage.review_path(500).read_text()
    op_lines = [l for l in text.splitlines() if l.lstrip().startswith('{"op"')]
    assert len(op_lines) == 1 and json.loads(op_lines[0].strip().rstrip(","))["auto"] is True
    assert json.loads(text)["ops"] == review["ops"]


# --- the real book ------------------------------------------------------------------

# Lines the maintainer flagged on fresh reviews of pp.518-519 (2026-11-17): the top of a
# capital or the descenders cut by Paddle's box. UI numbers are reading-order positions.
FLAGGED = {518: ["line_023", "line_029", "line_074"],
           519: ["line_017", "line_041", "line_047", "line_050", "line_055"]}


@pytest.mark.parametrize("pg", sorted(FLAGGED))
def test_flagged_lines_lose_no_ink(pg):
    if not (storage.render_path(pg).exists() and storage.baseline_path(pg).exists()):
        pytest.skip("page render or baseline not present")
    import cv2
    gray = cv2.imread(str(storage.render_path(pg)), cv2.IMREAD_GRAYSCALE)
    review = storage.new_review(pg)
    after = storage.materialized(pg, review)
    before = storage.materialized_page(
        pg, [o for o in review["ops"] if o["op"] != "reshape"], [])["lines"]
    for key in FLAGGED[pg]:
        i = next(n for n, l in enumerate(before) if l["key"] == key)
        j = next(n for n, l in enumerate(after) if l["key"] == key)
        assert unclip.ink_outside(before, i, gray) > 0, f"{key} wasn't cut to begin with"
        assert unclip.ink_outside(after, j, gray) == 0, key


# --- reopening verified pages with the unclip ops ----------------------------------------

def test_reopen_adds_the_ops_and_keeps_the_ids(store, monkeypatch):
    from dev.line_review import unclip_verified
    monkeypatch.setattr(storage, "VERIFIED_DIR", store / "verified")
    monkeypatch.setattr(storage, "BLANK_DIR", store / "blank")
    monkeypatch.setattr(storage, "MANIFEST_PATH", store / "baseline_sha256.json")
    storage.save_ops(500, [], [])                 # reviewed before unclip existed
    storage.set_status(500, "fixed")
    storage.set_status(500, "verified")
    ids = storage.load_review(500)["ids"]
    write_render(store, page(*BODY, (200, 110, 215, 168)))

    assert unclip_verified.reopen([500]) == {500: 1}
    review = storage.load_review(500)
    assert review["status"] == "fixed"
    assert [(o["op"], o["auto"]) for o in review["ops"]] == [("reshape", True)]
    storage.set_status(500, "verified")
    assert storage.load_review(500)["ids"] == ids

    assert unclip_verified.reopen([500]) == {}    # already unclipped: left alone


def test_reopen_skips_pages_not_verified(store):
    from dev.line_review import unclip_verified
    write_render(store, page(*BODY, (200, 110, 215, 168)))
    storage.save_ops(500, [], [])                 # fixing
    assert unclip_verified.reopen([500]) == {}
    assert storage.load_review(500)["status"] == "fixing"


@pytest.mark.parametrize("pg", [460, 506, 516, 539, 564])
def test_carved_boxes_stay_valid_polygons(pg):
    # Carved notches follow a letter's pixel outline; rounded to 0.1 px for the review
    # file they folded into self-intersections on 42 pages, which the materializer refuses.
    if not (storage.render_path(pg).exists() and storage.baseline_path(pg).exists()):
        pytest.skip("page render or baseline not present")
    review = storage.new_review(pg)
    for op in review["ops"]:
        if op["op"] == "reshape":
            assert Polygon(op["boundary"]).is_valid, op["line"]
    storage.materialized(pg, review)
