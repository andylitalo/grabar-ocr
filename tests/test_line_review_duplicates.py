"""
Tests for dropping Paddle's junk boxes before the review ops (dev.line_review.duplicates):
a line boxed twice keeps its larger copy, a box smaller than a character goes, and
anything a review op names is left for the reviewer. Ported from feat/layout-review.
"""

from __future__ import annotations

from dev.line_review import duplicates
from dev.line_review import materialize as mz

TWINS = [{"key": "a", "bbox": [1158, 2340, 1972, 2389]},
         {"key": "b", "bbox": [1160, 2394, 1970, 2443]},
         {"key": "c", "bbox": [1159, 2341, 1973, 2391]},   # a's twin, slightly larger
         {"key": "d", "bbox": [1160, 2440, 1970, 2540]}]   # b's neighbour, touching it


def keys(lines: list[dict]) -> list[str]:
    return [l["key"] for l in lines]


def as_seg_lines(lines: list[dict]) -> list[dict]:
    """Materializer lines for bare ``{key, bbox}`` boxes."""
    seg = {"lines": [{"id": l["key"], "bbox": l["bbox"], "source": "hyocr-paddle",
                      "boundary": [[l["bbox"][0], l["bbox"][1]], [l["bbox"][2], l["bbox"][1]],
                                   [l["bbox"][2], l["bbox"][3]], [l["bbox"][0], l["bbox"][3]]],
                      "baseline": [[l["bbox"][0], l["bbox"][3]], [l["bbox"][2], l["bbox"][3]]]}
                     for l in lines]}
    return mz.baseline_lines(seg)


def test_the_smaller_copy_of_a_line_boxed_twice_is_dropped():
    assert duplicates.pairs(TWINS) == [("c", "a")]
    assert keys(duplicates.dedupe(TWINS)) == ["b", "c", "d"]


def test_a_pair_the_reviewer_handled_is_left_alone():
    kept = lambda ops: keys(duplicates.dedupe(TWINS, ops))
    assert kept([{"op": "delete", "line": "a"}]) == ["a", "b", "c", "d"]   # p.473
    assert kept([{"op": "delete", "line": "c"}]) == ["a", "b", "c", "d"]
    assert kept([{"op": "initial", "line": "c", "box": [0, 0, 1, 1]}]) == ["b", "c", "d"]


def test_the_materializer_drops_copies_before_the_ops():
    assert sorted(keys(mz.materialize_page(as_seg_lines(TWINS), [])["lines"])) == ["b", "c", "d"]


def _rows(n: int = 5) -> list[dict]:
    return [{"key": f"r{i}", "bbox": [1000, 100 + 60 * i, 1800, 150 + 60 * i]} for i in range(n)]


def test_a_speck_inside_a_line_is_dropped():
    # p.485: "է", 20 x 12 px inside line_054. Its IoU with the line is ~0.01.
    lines = _rows() + [{"key": "speck", "bbox": [1170, 138, 1190, 150]}]
    assert keys(duplicates.dedupe(lines)) == [f"r{i}" for i in range(5)]


def test_a_box_smaller_than_a_character_is_dropped_but_thin_lines_and_letters_stay():
    lines = _rows() + [{"key": "speck", "bbox": [500, 500, 530, 525]},        # p.560
                       {"key": "thin", "bbox": [500, 600, 900, 620]},         # p.490
                       {"key": "letter", "bbox": [500, 700, 536, 745]}]       # p.641 cell
    assert duplicates.specks(lines) == ["speck"]
    assert "speck" in set(keys(duplicates.dedupe(lines, [{"op": "reshape", "line": "speck"}])))


def test_an_initials_tall_box_over_the_next_line_is_not_a_copy():
    # p.492: the drop cap made line 31's box reach down over line 32; the outlines don't meet.
    upper = {"key": "u", "bbox": [340, 2023, 1130, 2147],
             "boundary": [[340, 2023], [1130, 2023], [1130, 2110], [447, 2110], [447, 2147], [340, 2147]]}
    lower = {"key": "l", "bbox": [431, 2115, 1131, 2171],
             "boundary": [[447, 2115], [1131, 2115], [1131, 2171], [447, 2171]]}
    assert duplicates.pairs([upper, lower]) == [("u", "l")]
    assert duplicates.outline_pairs([upper, lower]) == []


def test_empty_page_has_no_duplicates_or_specks():
    assert duplicates.dedupe([]) == [] and duplicates.specks([]) == []
