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


def test_a_letter_split_between_two_boxes_belongs_to_neither():
    # Half in each box: neither owns it, so neither is flagged for it.
    split = (200, 140, 215, 190)
    assert overlap.foreign_ink([UPPER, LOWER], page(*UPPER_LETTERS, split, *LOWER_LETTERS)) == []


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

def test_the_page_payload_and_page_list_carry_the_flags(monkeypatch, tmp_path):
    import cv2
    from dev.line_review import app as app_mod
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
    client = TestClient(app_mod.app)
    d = client.get("/api/pages/500").json()
    assert [(f["line"], f["other"], f["px"]) for f in d["foreign_ink"]] == [(2, 1, 8 * 15)]
    assert client.get("/api/pages").json()["flagged"] == {"500": 1}


# --- the real book ------------------------------------------------------------------

# The 10 lines left after the unclip re-verify of pp.453-516 (2026-11-18), all Paddle's
# own boxes: the threshold was chosen to flag exactly these.
VERIFIED_FLAGS = {(459, "line_022"), (460, "line_024"), (467, "line_002"), (478, "line_031"),
                  (487, "line_060"), (487, "line_073"), (500, "line_005"), (500, "line_007"),
                  (509, "line_043"), (516, "line_006")}


def test_the_verified_pages_flag_the_known_ten():
    import cv2
    pages = range(453, 517)
    if not all(storage.render_path(p).exists() for p in pages if storage.baseline_path(p).exists()):
        pytest.skip("page renders not present")
    found = set()
    for pg in pages:
        if not storage.verified_path(pg).exists():
            continue
        review = storage.load_review(pg)
        gray = cv2.imread(str(storage.render_path(pg)), cv2.IMREAD_GRAYSCALE)
        found |= {(pg, f["line"]) for f in overlap.foreign_ink(storage.materialized(pg, review), gray)}
    assert found == VERIFIED_FLAGS
