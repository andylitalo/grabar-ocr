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

from data_prep.column_detector import detect_columns  # noqa: E402
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


if __name__ == "__main__":
    test_deskew_recovers_applied_skew()
    test_detect_two_columns_splits_at_gutter()
    test_blank_page_is_deferred()
    print("\nAll synthetic column-slicing tests passed.")
