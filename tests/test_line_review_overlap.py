"""
Tests for the foreign-ink warning (dev.line_review.overlap): a line is flagged when its
crop shows at least MIN_PX px of another line's letters, so the reviewer looks at it.

Synthetic pages: white images with black rectangles as letters, lines as boxes.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dev.line_review import crops, overlap, storage

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


UPPER = line("line_001", 40, 100, 300, 160)
LOWER = line("line_002", 40, 170, 300, 230)
UPPER_LETTERS = [(50, 110, 80, 150), (100, 110, 130, 150), (150, 110, 180, 150)]
LOWER_LETTERS = [(50, 180, 80, 220), (100, 180, 130, 220), (150, 180, 180, 220)]


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(overlap, "_flags", {})


def test_a_neighbours_descender_inside_the_box_is_flagged():
    # The upper line's descender runs into the lower box over rows 170-177: 8 x 15 = 120 px.
    desc = (200, 110, 215, 178)
    f = overlap.foreign_ink([UPPER, LOWER], page(*UPPER_LETTERS, desc, *LOWER_LETTERS))
    assert [(x["line"], x["other"], x["px"]) for x in f] == [("line_002", "line_001", 8 * 15)]
    assert all(170 <= y <= 177 for _, y in f[0]["pixels"])
    assert f[0]["spots"] == [[200, 170, 214, 177]]


def test_the_count_is_what_the_crop_shows():
    desc = (200, 110, 215, 178)
    gray = page(*UPPER_LETTERS, desc, *LOWER_LETTERS)
    f = overlap.foreign_ink([UPPER, LOWER], gray)
    crop = np.asarray(crops.line_crop(Image.fromarray(gray), LOWER, pad=0))
    x1, y1 = LOWER["bbox"][:2]
    shown = (crop[: 178 - y1, 200 - x1:215 - x1] < 128).sum()   # the descender's rows
    assert f[0]["px"] == shown


def test_boxes_overlapping_in_the_gap_are_not_flagged():
    # The boxes overlap by 20 px, but only blank paper lies in the overlap.
    lower = line("line_002", 40, 140, 300, 230)
    gray = page((50, 110, 80, 135), (100, 110, 130, 135), (50, 180, 80, 220), (100, 180, 130, 220))
    assert overlap.foreign_ink([UPPER, lower], gray) == []


def test_less_than_min_px_is_not_flagged():
    desc = (200, 110, 203, 172)   # 3 px wide, 2-3 rows into the lower box: < 10 px
    assert overlap.foreign_ink([UPPER, LOWER], page(*UPPER_LETTERS, desc, *LOWER_LETTERS)) == []


def test_growing_the_box_over_more_of_the_letter_keeps_it_flagged():
    # The lower box's top dragged up into the descender instead of down out of it: it now
    # holds 420 of the letter's 1,020 px, too much for unclip's rule to give the letter
    # to the upper line, but the crop shows more of it than before, so it stays flagged.
    desc = (200, 110, 215, 178)
    gray = page(*UPPER_LETTERS, desc, *LOWER_LETTERS)
    f = overlap.foreign_ink([UPPER, line("line_002", 40, 150, 300, 230)], gray)
    assert [(x["line"], x["other"], x["px"]) for x in f] == [("line_002", "line_001", 28 * 15)]


def test_shrinking_the_box_out_of_the_letter_clears_the_flag():
    desc = (200, 110, 215, 178)
    gray = page(*UPPER_LETTERS, desc, *LOWER_LETTERS)
    assert overlap.foreign_ink([UPPER, line("line_002", 40, 178, 300, 230)], gray) == []


# A letter exactly half in each box: rows 150-160 in the upper box, 170-180 in the lower.
TIED = (200, 150, 215, 181)


def test_a_letter_split_exactly_in_half_flags_one_of_the_two():
    f = overlap.foreign_ink([UPPER, LOWER], page(*UPPER_LETTERS, TIED, *LOWER_LETTERS))
    assert len(f) == 1 and f[0]["px"] == 11 * 15
    assert {f[0]["line"], f[0]["other"]} == {"line_001", "line_002"}


def test_the_tiebreak_is_the_same_on_every_run_and_in_any_line_order():
    gray = page(*UPPER_LETTERS, TIED, *LOWER_LETTERS)
    pick = lambda ls: [(x["line"], x["other"]) for x in overlap.foreign_ink(ls, gray)]
    assert pick([UPPER, LOWER]) == pick([UPPER, LOWER]) == pick([LOWER, UPPER])


def test_the_tiebreak_differs_from_letter_to_letter():
    # Seeded by the letter's position, not always the upper (or the first) line.
    winners = set()
    for x in range(190, 290, 6):
        gray = page(*UPPER_LETTERS, (x, 150, x + 5, 181), *LOWER_LETTERS)
        f = overlap.foreign_ink([UPPER, LOWER], gray)
        if f:
            winners.add(f[0]["other"])
    assert winners == {"line_001", "line_002"}


def test_flags_are_cached_until_the_edits_change(monkeypatch, tmp_path):
    import cv2
    monkeypatch.setattr(storage, "RENDER_DIR", tmp_path)
    monkeypatch.setattr(storage, "baseline_sha256", lambda pg: "sha")
    (tmp_path / "page_500").mkdir()
    cv2.imwrite(str(tmp_path / "page_500" / "render.png"),
                page(*UPPER_LETTERS, (200, 110, 215, 178), *LOWER_LETTERS))
    review = {"ops": [], "section_titles": []}
    calls = []
    real = overlap.foreign_ink
    monkeypatch.setattr(overlap, "foreign_ink", lambda *a: calls.append(1) or real(*a))
    assert len(overlap.page_flags(500, review, [UPPER, LOWER])) == 1
    overlap.page_flags(500, review, [UPPER, LOWER])
    assert len(calls) == 1
    overlap.page_flags(500, {"ops": [{"op": "delete", "line": "line_003"}]}, [UPPER, LOWER])
    assert len(calls) == 2
    assert overlap.flagged_counts() == {500: 1}


# --- the review app -------------------------------------------------------------------

@pytest.fixture
def one_page(monkeypatch, tmp_path):
    """Page 500 in a temporary store: UPPER and LOWER, LOWER showing UPPER's descender."""
    import cv2
    base = tmp_path / "baseline"
    (base / "page_500").mkdir(parents=True)
    seg = {"page": 500, "tool": "paddle-filled", "width": W, "height": H, "lines": [
        {"id": l["key"], "boundary": l["boundary"], "bbox": l["bbox"],
         "baseline": [[40, l["bbox"][3] - 15], [300, l["bbox"][3] - 15]], "source": "hyocr-paddle"}
        for l in (UPPER, LOWER)]}
    (base / "page_500" / "segmentation.json").write_text(json.dumps(seg))
    monkeypatch.setattr(storage, "BASELINE_DIR", base)
    monkeypatch.setattr(storage, "REVIEWS_DIR", tmp_path / "reviews")
    monkeypatch.setattr(storage, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "VERIFIED_DIR", tmp_path / "verified")
    monkeypatch.setattr(storage, "BLANK_DIR", tmp_path / "blank")
    monkeypatch.setattr(storage, "_unclip_cache", {})
    (tmp_path / "renders" / "page_500").mkdir(parents=True)
    # The descender is cut by its own box too, so unclip would take it in: start the
    # page with a saved review (no ops) to see Paddle's boxes as they are.
    cv2.imwrite(str(tmp_path / "renders" / "page_500" / "render.png"),
                page(*UPPER_LETTERS, (200, 110, 215, 178), *LOWER_LETTERS))
    storage.save_ops(500, [], [])
    monkeypatch.setattr(storage, "_page_cache", {})


def test_the_page_payload_and_page_list_carry_the_flags(one_page, monkeypatch):
    from dev.line_review import app as app_mod
    client = TestClient(app_mod.app)
    d = client.get("/api/pages/500").json()
    assert [(f["line"], f["other"], f["px"]) for f in d["foreign_ink"]] == [(2, 1, 8 * 15)]
    assert [(f["line_key"], f["other_key"]) for f in d["foreign_ink"]] == [("line_002", "line_001")]
    assert client.get("/api/pages").json()["flagged"] == {"500": 1}

    # A warning never stops the page loading (nor a save returning its payload).
    def broken(*a):
        raise RuntimeError("boom")
    monkeypatch.setattr(overlap, "page_flags", broken)
    r = client.get("/api/pages/500")
    assert r.status_code == 200 and r.json()["foreign_ink"] == [] and len(r.json()["lines"]) == 2


def test_warming_the_flags_leaves_the_page_cache_alone(one_page):
    # Going through every page would push the reviewer's out of the small page cache.
    overlap.warm()
    assert overlap.flagged_counts() == {500: 1}
    assert storage._page_cache == {}


# --- the real book ------------------------------------------------------------------

# The threshold (MIN_PX) was chosen on pp.453-516 after the unclip re-verify: it flagged
# exactly the 10 lines left then, all Paddle's own boxes (2026-11-18; PR #24). The review
# then fixed those 10 (2026-11-23), so no verified page shows another line's letters.


def test_no_verified_page_shows_another_lines_letters():
    import cv2
    pages = [p for p in storage.list_pages() if storage.verified_path(p).exists()]
    if not pages or not all(storage.render_path(p).exists() for p in pages):
        pytest.skip("page renders not present")
    found = []
    for pg in pages:
        lines = storage.materialized(pg, storage.load_review(pg), cache=False)
        if not lines:
            continue
        gray = cv2.imread(str(storage.render_path(pg)), cv2.IMREAD_GRAYSCALE)
        found += [(pg, f["line"], f["other"], f["px"]) for f in overlap.foreign_ink(lines, gray)]
    assert found == []
