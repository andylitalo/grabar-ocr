"""
Synthetic regression tests for the deskew + two-column detector.

No test framework is required: run directly with

    uv run python tests/test_column_slicing.py

(The functions are also plain ``test_*`` so pytest can collect them if added.)
The tests build a synthetic two-column page — text rows as dark bars, a gutter of
whitespace, and top/bottom rules — so the checks don't depend on real scans.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_prep.column_detector import (  # noqa: E402
    _longest_run_frac,
    _strip_edge_rule,
    detect_columns,
    detect_regions,
)
from data_prep.deskew import deskew_page, estimate_skew_angle  # noqa: E402


def _synthetic_page(width: int = 1600, height: int = 2200) -> np.ndarray:
    """White page with two columns of text-like bars, a gutter, and two rules."""
    page = np.full((height, width), 255, np.uint8)
    gutter_c = width // 2
    cols = [(int(0.08 * width), gutter_c - int(0.04 * width)),
            (gutter_c + int(0.04 * width), int(0.92 * width))]
    # Top and bottom decorative rules spanning the text block.
    cv2.rectangle(page, (cols[0][0], 150), (cols[1][1], 162), 0, -1)
    cv2.rectangle(page, (cols[0][0], height - 162), (cols[1][1], height - 150), 0, -1)
    # Text rows: dashes (word-like) at a fixed pitch within each column, between
    # the rules. Gaps keep each row's ink fraction well below a solid rule's, so
    # the rule detector isn't fooled (real text rows are ~20-30% ink per row).
    for x0, x1 in cols:
        for row, y in enumerate(range(210, height - 210, 46)):
            offset = (row * 13) % 40  # stagger so columns fill evenly across width
            for x in range(x0 + offset, x1 - 24, 40):
                cv2.rectangle(page, (x, y), (x + 24, y + 30), 40, -1)
    return page


def test_deskew_recovers_applied_skew() -> None:
    page = _synthetic_page()
    # Rotate the clean page by a known angle, then check we estimate ~its inverse.
    h, w = page.shape
    rot = cv2.getRotationMatrix2D((w / 2, h / 2), 2.0, 1.0)
    skewed = cv2.warpAffine(page, rot, (w, h), borderValue=255)
    est = estimate_skew_angle(skewed)
    assert abs(est - (-2.0)) < 0.3, f"expected ~-2.0 deg, got {est:.2f}"
    deskewed, applied = deskew_page(skewed)
    residual = estimate_skew_angle(deskewed)
    assert abs(residual) <= 0.15, f"residual skew too large: {residual:.2f}"
    print(f"deskew: estimated {est:.2f}, applied {applied:.2f}, residual {residual:.2f}  OK")


def test_detect_two_columns_splits_at_gutter() -> None:
    page = _synthetic_page(width=1600, height=2200)
    boxes, diag = detect_columns(page)
    assert diag["confident"], f"should be confident: {diag.get('reason')}"
    assert len(boxes) == 2
    # Gutter near the page center; boxes ordered left, right; no overlap.
    assert abs(diag["gutter_x"] - 800) < 60, diag["gutter_x"]
    assert boxes[0]["x2"] <= boxes[1]["x1"], "columns overlap"
    # y-extent excludes the rules (body sits between them, ~[162, 2038]).
    assert boxes[0]["y1"] >= 150 and boxes[0]["y2"] <= 2050
    print(f"detect: gutter={diag['gutter_x']} boxes={boxes}  OK")


def test_blank_page_is_deferred() -> None:
    blank = np.full((2200, 1600), 255, np.uint8)
    boxes, diag = detect_columns(blank)
    assert not diag["confident"] and boxes == []
    assert estimate_skew_angle(blank) == 0.0
    print("blank page deferred + zero skew  OK")


# --- Phase 6 region cases ----------------------------------------------------


def _fill_text(page, x0, x1, y0, y1, *, pitch=46, bar_h=30, bar_w=24, val=40) -> None:
    """Draw staggered text-like bars (word units) filling a rectangle."""
    for row, y in enumerate(range(y0, y1, pitch)):
        offset = (row * 13) % 40
        for x in range(x0 + offset, x1 - bar_w, 40):
            cv2.rectangle(page, (x, y), (x + bar_w, y + bar_h), val, -1)


def _two_columns(page, *, lx=(128, 736), rx=(864, 1472), y0=210, y1=1990) -> None:
    _fill_text(page, lx[0], lx[1], y0, y1)
    _fill_text(page, rx[0], rx[1], y0, y1)


def _max_edge_run(binary, box) -> float:
    """Longest contiguous foreground fraction over any of a box's four borders.

    A frame/divider rule on an edge lights up almost the whole border (run ~1.0);
    body text merely grazing the cut produces only short runs. So this flags rules,
    not the ordinary text that legitimately sits at a tight crop edge.
    """
    x1, y1, x2, y2 = box["x1"], box["y1"], box["x2"], box["y2"]
    x2c, y2c = min(x2, binary.shape[1] - 1), min(y2, binary.shape[0] - 1)
    borders = [binary[y1, x1:x2c], binary[y2c, x1:x2c],
               binary[y1:y2c, x1], binary[y1:y2c, x2c]]
    best = 0.0
    for arr in borders:
        run = longest = 0
        for v in (arr > 0):
            run = run + 1 if v else 0
            longest = max(longest, run)
        best = max(best, longest / max(1, len(arr)))
    return best


def test_frame_is_stripped_from_boxes() -> None:
    page = np.full((2200, 1600), 255, np.uint8)
    # full rectangular frame in the outer margin
    cv2.rectangle(page, (40, 40), (1560, 2160), 0, 6)
    _two_columns(page)
    regions, diag = detect_regions(page)
    assert diag["confident"], diag.get("reason")
    assert [r["type"] for r in regions] == ["left", "right"]
    # every box strictly inside the frame, with no frame *rule* on its edges
    # (text may legitimately graze a tight crop edge — only long runs are rules)
    binary = (page < 128).astype(np.uint8) * 255
    for r in regions:
        assert r["x1"] > 46 and r["x2"] < 1554, r
        assert r["y1"] > 46 and r["y2"] < 2154, r
        assert _max_edge_run(binary, r) < 0.5, ("frame rule on edge", r)
    print(f"frame stripped: {[ (r['x1'],r['x2']) for r in regions ]}  OK")


def test_central_divider_excluded() -> None:
    page = np.full((2200, 1600), 255, np.uint8)
    _two_columns(page)
    # vertical divider rule in the gutter centre
    cv2.rectangle(page, (797, 210), (803, 1990), 0, -1)
    regions, diag = detect_regions(page)
    assert diag["confident"], diag.get("reason")
    assert [r["type"] for r in regions] == ["left", "right"]
    left, right = regions
    # the divider column (x≈800) is inside NEITHER box
    assert not (left["x1"] <= 800 <= left["x2"]), left
    assert not (right["x1"] <= 800 <= right["x2"]), right
    assert left["x2"] <= right["x1"], "columns overlap"
    print(f"divider excluded: left.x2={left['x2']} right.x1={right['x1']}  OK")


def test_marginal_number_excluded() -> None:
    page = np.full((2200, 1600), 255, np.uint8)
    # body columns shifted in; a footnote number sits in the far-left margin with a
    # clear gap from the body so it is a separate (short) projection run.
    _two_columns(page, lx=(180, 740), rx=(870, 1430))
    _fill_text(page, 40, 95, 980, 1080)  # marginal note digits
    regions, diag = detect_regions(page)
    assert diag["confident"], diag.get("reason")
    assert [r["type"] for r in regions] == ["left", "right"]
    left = regions[0]
    assert left["x1"] > 110, ("marginal number pulled into left column", left)
    print(f"marginalia excluded: left.x1={left['x1']}  OK")


def test_header_band_detected_before_columns() -> None:
    page = np.full((2200, 1600), 255, np.uint8)
    # a large-type single-column heading at the top, set off by a gap
    _fill_text(page, 300, 1300, 110, 230, pitch=70, bar_h=56, bar_w=44)
    _two_columns(page, y0=420, y1=2040)
    regions, diag = detect_regions(page)
    assert diag["confident"], diag.get("reason")
    assert [r["type"] for r in regions] == ["header", "left", "right"], [r["type"] for r in regions]
    assert [r["order"] for r in regions] == [1, 2, 3]
    # header sits above the columns
    assert regions[0]["y2"] <= regions[1]["y1"], "header overlaps body band"
    print(f"header detected: body_lh={diag.get('body_line_height')}  OK")


def test_fused_header_defers_not_misslices() -> None:
    """A full-width band fused atop the columns (no separating gap) is NOT a clean
    two-column page: the gutter-purity guard must DEFER it, never mis-slice as 2-col."""
    page = np.full((2200, 1600), 255, np.uint8)
    # a solid full-width heading block crossing the gutter, directly above the body
    # with no whitespace gap, so band segmentation fuses it into the two-column band
    cv2.rectangle(page, (200, 210), (1400, 360), 60, -1)
    _two_columns(page, y0=380, y1=2000)
    regions, diag = detect_regions(page)
    assert not diag["confident"], ("should defer", diag.get("reason"))
    assert "gutter" in diag.get("reason", ""), diag.get("reason")
    assert regions == []
    # back-compat path defers too (so auto_slice skips it -> manual annotation)
    boxes, cdiag = detect_columns(page)
    assert not cdiag["confident"] and boxes == []
    print(f"fused header defers: run={diag.get('gutter_run_lh')}× lh  OK")


def test_strip_edge_rule_trims_dashed_rule_only() -> None:
    """The contiguous-run edge trim removes a (degraded) rule on an edge but leaves
    clean edges and ordinary text untouched."""
    binary = np.zeros((100, 200), np.uint8)
    binary[10:14, 20:60] = 255    # a 'word' on the top edge: run 40/200 = 0.2 (kept)
    binary[97:100, 8:188] = 255    # a rule ON the bottom edge: run 180/200 = 0.9 (trim)
    y1, y2 = _strip_edge_rule(binary, 0, 0, 200, 100)
    assert y2 <= 96, f"bottom rule not trimmed (y2={y2})"
    assert y1 == 0, f"top edge has no rule but was trimmed (y1={y1})"
    assert _longest_run_frac(binary[min(y2, 99), 0:200] > 0) < 0.5, "edge still a rule"
    # a box with no edge rule is a no-op
    clean = np.zeros((100, 200), np.uint8)
    clean[40:60, 20:60] = 255
    assert _strip_edge_rule(clean, 0, 0, 200, 100) == (0, 100)
    print("edge-rule trim: dashed rule removed, clean edges untouched  OK")


def test_single_column_page_is_confident() -> None:
    page = np.full((2200, 1600), 255, np.uint8)
    _fill_text(page, 220, 1380, 210, 1990)
    regions, diag = detect_regions(page)
    assert diag["confident"], diag.get("reason")
    assert [r["type"] for r in regions] == ["single"], [r["type"] for r in regions]
    # a single-column page no longer force-splits or defers
    boxes, cdiag = detect_columns(page)
    assert not cdiag["confident"] and boxes == [], "single page must not pose as two columns"
    print(f"single column confident: x=({regions[0]['x1']},{regions[0]['x2']})  OK")


if __name__ == "__main__":
    test_deskew_recovers_applied_skew()
    test_detect_two_columns_splits_at_gutter()
    test_blank_page_is_deferred()
    test_frame_is_stripped_from_boxes()
    test_central_divider_excluded()
    test_marginal_number_excluded()
    test_header_band_detected_before_columns()
    test_fused_header_defers_not_misslices()
    test_strip_edge_rule_trims_dashed_rule_only()
    test_single_column_page_is_confident()
    print("\nAll synthetic column-slicing tests passed.")
