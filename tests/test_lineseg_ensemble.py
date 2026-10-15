"""
Unit tests for dev.lineseg_survey.ensemble.insert_in_order: where a filled (or
human-drawn) line joins an already-ordered page.

Pure Python: no cv2 / numpy, runs in the BASE env.
"""

from __future__ import annotations

import pytest

from dev.lineseg_survey.ensemble import insert_in_order

# A two-column page at 300 DPI: left column x 100-950, right column x 1050-1900.
LEFT, RIGHT, FULL = (100, 950), (1050, 1900), (100, 1900)


def line(key: str, cols: tuple[float, float], y: float, h: float = 60) -> dict:
    return {"key": key, "bbox": [cols[0], y, cols[1], y + h]}


def order_after_insert(base: list[dict], add: dict) -> list[str]:
    out = list(base)
    out.insert(insert_in_order(out, add), add)
    return [l["key"] for l in out]


# --- the bug: a full-width line above is not the fill's column ---------------------


def test_top_of_right_column_under_header_goes_after_left_column():
    base = [line("hdr", FULL, 50), line("L1", LEFT, 200), line("L2", LEFT, 300),
            line("R2", RIGHT, 300), line("R3", RIGHT, 400)]
    assert order_after_insert(base, line("R1", RIGHT, 200)) == \
        ["hdr", "L1", "L2", "R1", "R2", "R3"]


def test_top_of_right_column_in_second_band_goes_after_that_bands_left_column():
    base = [line("L1", LEFT, 200), line("R1", RIGHT, 200),
            line("div", FULL, 400),
            line("L3", LEFT, 600), line("L4", LEFT, 700), line("R4", RIGHT, 700)]
    assert order_after_insert(base, line("R3", RIGHT, 600)) == \
        ["L1", "R1", "div", "L3", "L4", "R3", "R4"]


def test_only_line_of_right_column_in_a_band_goes_before_the_next_divider():
    base = [line("hdr", FULL, 50), line("L1", LEFT, 200), line("L2", LEFT, 300),
            line("div", FULL, 500), line("L5", LEFT, 700), line("L6", LEFT, 800),
            line("R5", RIGHT, 700), line("R6", RIGHT, 800)]
    assert order_after_insert(base, line("R1", RIGHT, 200)) == \
        ["hdr", "L1", "L2", "R1", "div", "L5", "L6", "R5", "R6"]


# --- behaviour the fix must not change ---------------------------------------------


@pytest.mark.parametrize("y, expected", [
    (100, ["N0", "A", "B", "C"]),
    (250, ["A", "N0", "B", "C"]),
    (550, ["A", "B", "C", "N0"]),
])
def test_single_column(y, expected):
    base = [line("A", LEFT, 150), line("B", LEFT, 350), line("C", LEFT, 450)]
    assert order_after_insert(base, line("N0", LEFT, y)) == expected


def test_top_of_left_column_under_header():
    base = [line("hdr", FULL, 50), line("L2", LEFT, 300), line("R1", RIGHT, 200),
            line("R2", RIGHT, 300)]
    assert order_after_insert(base, line("L1", LEFT, 200)) == ["hdr", "L1", "L2", "R1", "R2"]


def test_middle_of_right_column():
    base = [line("hdr", FULL, 50), line("L1", LEFT, 200), line("L2", LEFT, 300),
            line("R1", RIGHT, 200), line("R3", RIGHT, 400)]
    assert order_after_insert(base, line("R2", RIGHT, 300)) == \
        ["hdr", "L1", "L2", "R1", "R2", "R3"]


# --- known limits (Phase 8 doc §5.8); strict xfail flips to a failure once fixed -------


@pytest.mark.xfail(strict=True, reason="known gap (§5.8): a full-width fill joins after the "
                   "nearest line above in either column, not after the whole band")
def test_full_width_fill_between_bands():
    base = [line("L1", LEFT, 200), line("R1", RIGHT, 200),
            line("L3", LEFT, 600), line("R3", RIGHT, 600)]
    assert order_after_insert(base, line("div", FULL, 400)) == ["L1", "R1", "div", "L3", "R3"]


@pytest.mark.xfail(strict=True, reason="known gap (§5.8): a short box above the fill that "
                   "doesn't overlap it in x is skipped, so the fill is read before it")
def test_short_box_above_off_to_one_side():
    base = [line("A", LEFT, 150), line("B", (100, 400), 250), line("C", LEFT, 450)]
    assert order_after_insert(base, line("N0", (800, 950), 350)) == ["A", "B", "N0", "C"]


def test_header_over_too_few_lines_for_a_gutter_keeps_old_placement():
    # No gutter can be found with one line in the right column, so the header anchors.
    base = [line("hdr", FULL, 50), line("L1", LEFT, 200), line("L2", LEFT, 300),
            line("R2", RIGHT, 300)]
    assert order_after_insert(base, line("R1", RIGHT, 200)) == ["hdr", "R1", "L1", "L2", "R2"]


def test_no_line_shares_the_column_falls_back_to_y():
    base = [line("A", (100, 500), 100), line("B", (100, 500), 400)]
    assert order_after_insert(base, line("N0", (1400, 1900), 250)) == ["A", "N0", "B"]


def test_empty_page():
    assert insert_in_order([], line("N0", LEFT, 100)) == 0
