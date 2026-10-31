"""
Unit tests for the Phase 9 materializer (dev.line_review.materialize): baseline
segmentation + ordered review ops -> final lines, plus stable line-id minting.

Pure geometry (shapely) + JSON; no page images.
"""

from __future__ import annotations

import json

import pytest
from shapely.geometry import Point, Polygon

from dev.line_review import materialize as mz


def rect(x1: float, y1: float, x2: float, y2: float) -> list[list[float]]:
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def seg_line(lid: str, box: list[float], source: str = "hyocr-paddle") -> dict:
    x1, y1, x2, y2 = box
    y = y1 + 0.75 * (y2 - y1)
    line = {"id": lid, "boundary": rect(*box), "baseline": [[x1, y], [x2, y]],
            "bbox": list(box), "source": source}
    if source == "kraken-fill":
        line["kraken_id"] = "line_099"
    return line


# Two-column page: left column lines 1-3, right column lines 4-5.
SEG = {
    "page": 500, "tool": "paddle-filled", "width": 2000, "height": 3000,
    "lines": [
        seg_line("line_001", [100, 100, 900, 150]),
        seg_line("line_002", [100, 200, 900, 250]),
        seg_line("line_003", [100, 300, 900, 350], source="kraken-fill"),
        seg_line("line_004", [1100, 100, 1900, 150]),
        seg_line("line_005", [1100, 200, 1900, 250]),
    ],
}


def keys(lines: list[dict]) -> list[str]:
    return [l["key"] for l in lines]


def run(ops: list[dict]) -> list[dict]:
    return mz.apply_ops(mz.baseline_lines(SEG), ops)


# --- baseline -------------------------------------------------------------------


def test_no_ops_returns_baseline_in_order():
    lines = run([])
    assert keys(lines) == ["line_001", "line_002", "line_003", "line_004", "line_005"]
    assert lines[0]["baseline_source"] == "synthetic"
    assert lines[2]["baseline_source"] == "kraken"
    assert lines[2]["source"] == "kraken-fill"
    assert lines[0]["derived_from"] == ["line_001"]


# --- delete / add / reshape ----------------------------------------------------------


def test_delete_removes_line():
    assert keys(run([{"op": "delete", "line": "line_002"}])) == [
        "line_001", "line_003", "line_004", "line_005"]


def test_add_slots_into_its_column_by_position():
    lines = run([{"op": "add", "key": "add_001", "boundary": rect(1100, 300, 1900, 350)}])
    assert keys(lines) == ["line_001", "line_002", "line_003", "line_004", "line_005", "add_001"]
    added = lines[-1]
    assert added["source"] == "human"
    assert added["baseline_source"] == "synthetic"
    assert added["derived_from"] == []
    lines = run([{"op": "add", "key": "add_001", "boundary": rect(100, 160, 900, 190)}])
    assert keys(lines)[:3] == ["line_001", "add_001", "line_002"]


def test_reshape_replaces_polygon_and_bbox():
    lines = run([{"op": "reshape", "line": "line_001", "boundary": rect(90, 95, 910, 160)}])
    assert lines[0]["key"] == "line_001"
    assert lines[0]["bbox"] == [90, 95, 910, 160]
    assert lines[0]["baseline_source"] == "synthetic"
    assert lines[0]["baseline"] == [[90, 143.75], [910, 143.75]]


def test_reshape_keeps_kraken_baseline_while_it_still_fits():
    lines = run([{"op": "reshape", "line": "line_003", "boundary": rect(95, 295, 905, 355)}])
    assert lines[2]["baseline_source"] == "kraken"
    lines = run([{"op": "reshape", "line": "line_003", "boundary": rect(100, 300, 900, 330)}])
    assert lines[2]["baseline_source"] == "synthetic"


# --- split ---------------------------------------------------------------------------


def test_vertical_split_names_halves_left_to_right():
    lines = run([{"op": "split", "line": "line_001", "cut": [[500, 90], [500, 160]]}])
    assert keys(lines)[:2] == ["line_001/1", "line_001/2"]
    left, right = lines[0], lines[1]
    assert left["bbox"][2] == pytest.approx(500)
    assert right["bbox"][0] == pytest.approx(500)
    assert left["derived_from"] == ["line_001"]


def test_horizontal_split_names_halves_top_to_bottom():
    lines = run([{"op": "split", "line": "line_002", "cut": [[90, 225], [910, 225]]}])
    assert keys(lines)[1:3] == ["line_002/1", "line_002/2"]
    assert lines[1]["bbox"][3] == pytest.approx(225)


def test_gutter_split_puts_right_half_in_right_column_order():
    # A header fused across the gutter: the right half belongs before line_004.
    seg = {**SEG, "lines": [seg_line("line_000", [100, 40, 1900, 90])] + SEG["lines"]}
    lines = mz.apply_ops(mz.baseline_lines(seg),
                         [{"op": "split", "line": "line_000", "cut": [[1000, 30], [1000, 100]]}])
    ks = keys(lines)
    assert ks.index("line_000/1") < ks.index("line_001")
    assert ks.index("line_000/2") == ks.index("line_004") - 1


def test_split_that_does_not_cross_the_line_is_rejected():
    with pytest.raises(mz.OpError):
        run([{"op": "split", "line": "line_001", "cut": [[500, 90], [500, 120]]}])


# --- merge / initial -------------------------------------------------------------------


def test_merge_unions_lines_under_a_joint_key_at_first_position():
    lines = run([{"op": "merge", "lines": ["line_001", "line_002"]}])
    assert keys(lines) == ["line_001+line_002", "line_003", "line_004", "line_005"]
    assert lines[0]["bbox"] == [100, 100, 900, 250]
    assert lines[0]["derived_from"] == ["line_001", "line_002"]


def test_initial_grows_target_and_carves_others():
    # Drop-cap spanning lines 1-2 on their left; assigned to line_001.
    lines = run([{"op": "initial", "box": [40, 100, 140, 250], "line": "line_001", "letter": "Ա"}])
    assert lines[0]["bbox"][0] == 40
    assert lines[1]["bbox"][0] == pytest.approx(140)  # line_002 lost the overlap


# --- order / annotations / errors --------------------------------------------------------


def test_order_op_sets_explicit_permutation():
    order = ["line_004", "line_005", "line_001", "line_002", "line_003"]
    assert keys(run([{"op": "order", "lines": order}])) == order


def test_order_op_must_be_a_permutation():
    with pytest.raises(mz.OpError):
        run([{"op": "order", "lines": ["line_001", "line_002"]}])


def test_dismiss_ink_does_not_change_lines():
    assert keys(run([{"op": "dismiss_ink", "box": [0, 0, 10, 10]}])) == keys(run([]))


def test_unknown_line_reference_is_rejected():
    with pytest.raises(mz.OpError):
        run([{"op": "delete", "line": "line_404"}])
    with pytest.raises(mz.OpError):
        run([{"op": "delete", "line": "line_001"}, {"op": "delete", "line": "line_001"}])


def test_duplicate_add_key_is_rejected():
    with pytest.raises(mz.OpError):
        run([{"op": "add", "key": "line_001", "boundary": rect(0, 0, 10, 10)}])


def test_ops_compose_on_derived_keys():
    lines = run([
        {"op": "split", "line": "line_001", "cut": [[500, 90], [500, 160]]},
        {"op": "delete", "line": "line_001/2"},
    ])
    assert keys(lines)[:2] == ["line_001/1", "line_002"]


# --- id minting ---------------------------------------------------------------------------


def test_first_verify_mints_ids_in_reading_order():
    state = mz.mint_ids(500, run([]), mz.empty_id_state())
    assert state["ids"] == {f"line_00{i}": f"p500.00{i}" for i in range(1, 6)}
    assert state["next_seq"] == 6
    assert state["retired"] == {}


def test_reverify_keeps_ids_and_appends_new_lines():
    first = mz.mint_ids(500, run([]), mz.empty_id_state())
    lines = run([{"op": "add", "key": "add_001", "boundary": rect(100, 160, 900, 190)}])
    state = mz.mint_ids(500, lines, first)
    assert state["ids"]["line_002"] == "p500.002"
    assert state["ids"]["add_001"] == "p500.006"
    assert state["next_seq"] == 7


def test_split_and_delete_retire_ids_with_successors():
    first = mz.mint_ids(500, run([]), mz.empty_id_state())
    lines = run([
        {"op": "split", "line": "line_001", "cut": [[500, 90], [500, 160]]},
        {"op": "delete", "line": "line_005"},
    ])
    state = mz.mint_ids(500, lines, first)
    assert state["retired"]["p500.001"] == {"superseded_by": ["p500.006", "p500.007"]}
    assert state["retired"]["p500.005"] == {"superseded_by": []}
    assert "line_001" not in state["ids"]


def test_restored_line_gets_its_old_id_back():
    first = mz.mint_ids(500, run([]), mz.empty_id_state())
    second = mz.mint_ids(500, run([{"op": "delete", "line": "line_005"}]), first)
    third = mz.mint_ids(500, run([]), second)
    assert third["ids"]["line_005"] == "p500.005"
    assert "p500.005" not in third["retired"]
    assert third["next_seq"] == 6


def test_ids_are_never_reused():
    first = mz.mint_ids(500, run([]), mz.empty_id_state())
    second = mz.mint_ids(500, run([{"op": "delete", "line": "line_005"}]), first)
    lines = run([{"op": "delete", "line": "line_005"},
                 {"op": "add", "key": "add_001", "boundary": rect(1100, 200, 1900, 250)}])
    third = mz.mint_ids(500, lines, second)
    assert third["ids"]["add_001"] == "p500.006"


# --- verified record ------------------------------------------------------------------------


def test_verified_record_is_deterministic_and_carries_ids():
    lines = run([])
    review = {"page": 500, "status": "verified", "ops": [], "verified_at": "2026-10-02T00:00:00+00:00",
              **mz.mint_ids(500, lines, mz.empty_id_state())}
    a = mz.dumps(mz.verified_record(SEG, review, baseline_sha256="abc"))
    b = mz.dumps(mz.verified_record(SEG, review, baseline_sha256="abc"))
    assert a == b
    rec = json.loads(a)
    assert [l["id"] for l in rec["lines"]] == [f"p500.00{i}" for i in range(1, 6)]
    assert [l["order"] for l in rec["lines"]] == [1, 2, 3, 4, 5]
    assert rec["baseline"] == {"tool": "paddle-filled", "sha256": "abc"}


def test_verified_record_requires_an_id_for_every_line():
    review = {"page": 500, "status": "verified", "verified_at": "x",
              "ops": [{"op": "add", "key": "add_001", "boundary": rect(100, 160, 900, 190)}],
              **mz.mint_ids(500, run([]), mz.empty_id_state())}
    with pytest.raises(mz.OpError):
        mz.verified_record(SEG, review, baseline_sha256="abc")


def test_grow_adds_an_area_to_a_line_and_carves_neighbours():
    # Ink above line_002 that it missed, overlapping line_001's bottom edge.
    lines = run([{"op": "grow", "line": "line_002", "box": [300, 140, 500, 210]}])
    assert lines[1]["key"] == "line_002"
    assert lines[1]["bbox"][1] == 140
    notched = Polygon(lines[0]["boundary"])  # line_001 loses the overlap, keeps the rest
    assert not notched.contains(Point(400, 145))
    assert notched.contains(Point(200, 145))
    assert keys(lines) == keys(run([]))


def test_initial_with_a_gap_bridges_within_the_target_row_only():
    # Drop-cap box ends at x=90, short of line_001 (x>=100), and reaches down past line_002.
    lines = run([{"op": "initial", "box": [20, 100, 90, 250], "line": "line_001", "letter": "Ա"}])
    target, below = Polygon(lines[0]["boundary"]), Polygon(lines[1]["boundary"])
    assert target.contains(Point(55, 240))     # the cap's foot is in the target...
    assert not target.contains(Point(500, 225))  # ...but no hull across line_002's text
    assert target.intersection(below).area == 0


# --- page elements: page number, initial letters, section titles -------------------------


def test_page_number_takes_a_line_out_of_the_text():
    page = mz.materialize_page(mz.baseline_lines(SEG), [
        {"op": "page_number", "line": "line_004", "value": "496"}])
    assert "line_004" not in keys(page["lines"])
    assert page["page_number"] == {"value": "496", "box": [1100, 100, 1900, 150]}


def test_page_number_can_be_a_drawn_box():
    page = mz.materialize_page(mz.baseline_lines(SEG), [
        {"op": "page_number", "box": [950, 20, 1050, 60], "value": "496"}])
    assert keys(page["lines"]) == keys(run([]))
    assert page["page_number"]["box"] == [950, 20, 1050, 60]


def test_only_one_page_number_per_page():
    with pytest.raises(mz.OpError):
        run([{"op": "page_number", "line": "line_004", "value": "496"},
             {"op": "page_number", "line": "line_005", "value": "497"}])
    with pytest.raises(mz.OpError):
        run([{"op": "page_number", "line": "line_004", "value": " "}])


def test_initial_letter_is_kept_on_its_line():
    lines = run([{"op": "initial", "box": [40, 100, 140, 250], "line": "line_001", "letter": "Ա"}])
    assert lines[0]["initial"] == "Ա"
    assert "initial" not in lines[1]
    grown = run([{"op": "grow", "box": [40, 100, 140, 250], "line": "line_001"}])
    assert "initial" not in grown[0]


def test_verified_record_carries_page_elements():
    ops = [{"op": "page_number", "line": "line_004", "value": "496"},
           {"op": "initial", "box": [40, 100, 140, 250], "line": "line_001", "letter": "Ա"}]
    lines = run(ops)
    review = {"page": 500, "status": "verified", "ops": ops, "verified_at": "x",
              "section_titles": [{"id": "title_001", "letter": "Դ", "box": [10, 10, 60, 60],
                                  "source_line": None}],
              **mz.mint_ids(500, lines, mz.empty_id_state())}
    rec = mz.verified_record(SEG, review, baseline_sha256="abc")
    assert rec["page_number"] == {"value": "496", "box": [1100, 100, 1900, 150]}
    assert rec["section_titles"] == [{"letter": "Դ", "box": [10, 10, 60, 60]}]
    assert rec["lines"][0]["initial"] == "Ա"
    assert rec["lines"][1]["initial"] is None
    assert len(rec["lines"]) == 4


# --- reading order: column first --------------------------------------------------------


def _page(lines: list[tuple[str, list[float]]]) -> list[dict]:
    seg = {**SEG, "lines": [seg_line(k, b) for k, b in lines]}
    return mz.baseline_lines(seg)


def test_columns_read_top_to_bottom_before_the_next_column():
    # Baseline order cuts across: a block of both columns, then the next block of both.
    lines = _page([
        ("a1", [100, 100, 900, 150]), ("a2", [100, 200, 900, 250]),
        ("b1", [1100, 100, 1900, 150]), ("b2", [1100, 200, 1900, 250]),
        ("a3", [100, 400, 900, 450]), ("a4", [100, 500, 900, 550]),
        ("b3", [1100, 400, 1900, 450]), ("b4", [1100, 500, 1900, 550]),
    ])
    assert keys(mz.apply_ops(lines, [])) == ["a1", "a2", "a3", "a4", "b1", "b2", "b3", "b4"]


def test_full_width_lines_divide_the_page_into_bands():
    lines = _page([
        ("a1", [100, 100, 900, 150]), ("b1", [1100, 100, 1900, 150]),
        ("a2", [100, 200, 900, 250]), ("b2", [1100, 200, 1900, 250]),
        ("a3", [100, 300, 900, 350]), ("b3", [1100, 300, 1900, 350]),
        ("title", [300, 400, 1700, 460]),
        ("c1", [100, 500, 900, 550]), ("d1", [1100, 500, 1900, 550]),
    ])
    assert keys(mz.apply_ops(lines, [])) == ["a1", "a2", "a3", "b1", "b2", "b3", "title", "c1", "d1"]


def test_boxes_on_a_full_width_row_read_left_to_right():
    # A title split in two pieces plus a section number on the same row.
    lines = _page([
        ("a1", [100, 100, 900, 150]), ("a2", [100, 200, 900, 250]), ("a3", [100, 300, 900, 350]),
        ("b1", [1100, 100, 1900, 150]), ("b2", [1100, 200, 1900, 250]), ("b3", [1100, 300, 1900, 350]),
        ("num", [1750, 402, 1850, 458]), ("t2", [800, 401, 1600, 459]), ("t1", [300, 400, 790, 460]),
    ])
    assert keys(mz.apply_ops(lines, []))[-3:] == ["t1", "t2", "num"]


def test_drop_cap_box_comes_before_the_line_beside_it():
    lines = _page([
        ("a1", [100, 100, 900, 150]), ("line", [200, 200, 900, 250]), ("cap", [100, 200, 190, 320]),
        ("a3", [100, 330, 900, 380]),
        ("b1", [1100, 100, 1900, 150]), ("b2", [1100, 200, 1900, 250]), ("b3", [1100, 300, 1900, 350]),
    ])
    assert keys(mz.apply_ops(lines, []))[:4] == ["a1", "cap", "line", "a3"]


def test_an_order_op_overrides_the_column_rule():
    order = ["line_004", "line_005", "line_001", "line_002", "line_003"]
    lines = run([{"op": "order", "lines": order},
                 {"op": "add", "key": "add_001", "boundary": rect(1100, 300, 1900, 350)}])
    # the explicit order stands; a line added afterwards slots into its column
    assert keys(lines) == ["line_004", "line_005", "add_001", "line_001", "line_002", "line_003"]


TWO_BLOCKS = [  # both columns, a gap at y 260-390 with no line across it
    ("a1", [100, 100, 900, 150]), ("a2", [100, 200, 900, 250]),
    ("b1", [1100, 100, 1900, 150]), ("b2", [1100, 200, 1900, 250]),
    ("a3", [100, 400, 900, 450]), ("a4", [100, 500, 900, 550]),
    ("b3", [1100, 400, 1900, 450]), ("b4", [1100, 500, 1900, 550]),
]


def test_a_gutter_break_splits_the_page_before_the_columns():
    page = mz.materialize_page(_page(TWO_BLOCKS), [{"op": "break", "y": 320}])
    assert keys(page["lines"]) == ["a1", "a2", "b1", "b2", "a3", "a4", "b3", "b4"]


def test_a_section_title_on_the_gutter_is_a_break():
    titles = [{"letter": "Դ", "box": [970, 280, 1030, 370]}]
    page = mz.materialize_page(_page(TWO_BLOCKS), [], section_titles=titles)
    assert keys(page["lines"]) == ["a1", "a2", "b1", "b2", "a3", "a4", "b3", "b4"]


def test_a_section_title_inside_one_column_is_not_a_break():
    titles = [{"letter": "Դ", "box": [400, 280, 460, 370]}]
    page = mz.materialize_page(_page(TWO_BLOCKS), [], section_titles=titles)
    assert keys(page["lines"]) == ["a1", "a2", "a3", "a4", "b1", "b2", "b3", "b4"]


# --- merge across a gap ----------------------------------------------------------------


def lines_of(*boxes: tuple[str, list[float]]) -> list[dict]:
    return mz.baseline_lines({"lines": [seg_line(k, b) for k, b in boxes]})


def test_merge_across_a_line_that_cuts_the_gap_is_refused():
    with pytest.raises(mz.OpError, match="line_002.*cut"):
        run([{"op": "merge", "lines": ["line_001", "line_003"]}])


def test_merge_takes_the_gap_but_not_a_line_poking_into_it():
    lines = lines_of(("a", [100, 100, 500, 150]), ("b", [700, 300, 900, 350]),
                     ("c", [520, 0, 650, 160]))
    out = mz.apply_ops(lines, [{"op": "merge", "lines": ["a", "b"]}])
    merged = Polygon(next(l for l in out if l["key"] == "a+b")["boundary"])
    assert merged.intersection(Polygon(rect(520, 0, 650, 160))).area == pytest.approx(0, abs=1)
    for box in ([100, 100, 500, 150], [700, 300, 900, 350]):
        assert merged.buffer(0.01).covers(Polygon(rect(*box)))
    assert merged.covers(Point(600, 225))  # the blank gap between them is taken in


def test_merge_around_an_enclosed_line_is_refused():
    lines = lines_of(("a", [100, 100, 500, 150]), ("b", [700, 300, 900, 350]),
                     ("c", [450, 200, 650, 240]))
    with pytest.raises(mz.OpError, match="'c'.*inside"):
        mz.apply_ops(lines, [{"op": "merge", "lines": ["a", "b"]}])


def test_merge_across_a_clear_gap_is_the_hull():
    out = run([{"op": "merge", "lines": ["line_001", "line_002"]}])
    assert out[0]["key"] == "line_001+line_002"
    assert out[0]["bbox"] == [100, 100, 900, 250]


def test_merge_of_kraken_lines_keeps_a_kraken_baseline():
    seg = {"lines": [seg_line("a", [100, 100, 500, 150], "kraken-fill"),
                     seg_line("b", [500, 100, 900, 150], "kraken-fill")]}
    out = mz.apply_ops(mz.baseline_lines(seg), [{"op": "merge", "lines": ["a", "b"]}])
    assert out[0]["baseline_source"] == "kraken"
    assert [p[0] for p in out[0]["baseline"]] == [100, 500, 500, 900]


def test_merge_keeps_an_initial_letter():
    out = run([{"op": "initial", "box": [60, 200, 99, 250], "line": "line_002", "letter": "Ա"},
               {"op": "merge", "lines": ["line_001", "line_002"]}])
    assert out[0]["initial"] == "Ա"


@pytest.mark.parametrize("keys_", [["line_001"], ["line_001", "line_001"]])
def test_merge_needs_two_distinct_lines(keys_):
    with pytest.raises(mz.OpError, match="2 distinct"):
        run([{"op": "merge", "lines": keys_}])


# --- kraken baseline after a reshape ---------------------------------------------------


def test_trimmed_kraken_line_keeps_its_baseline_cut_to_the_box():
    lines = run([{"op": "reshape", "line": "line_003", "boundary": rect(500, 300, 900, 350)}])
    l3 = next(l for l in lines if l["key"] == "line_003")
    assert l3["baseline_source"] == "kraken"
    assert l3["baseline"] == [[500, 337.5], [900, 337.5]]


def test_kraken_baseline_inside_the_new_box_is_untouched():
    lines = run([{"op": "reshape", "line": "line_003", "boundary": rect(50, 290, 950, 360)}])
    l3 = next(l for l in lines if l["key"] == "line_003")
    assert l3["baseline"] == SEG["lines"][2]["baseline"]


# --- section titles ----------------------------------------------------------------------


@pytest.mark.parametrize("letter", ["Ա", "ժբ", "ԺԲ"])
def test_armenian_title_letters_are_accepted(letter):
    mz.materialize_page(mz.baseline_lines(SEG), [], [{"letter": letter, "box": [10, 10, 50, 50]}])


@pytest.mark.parametrize("letter", ["", "A", "Ա Բ", "Ա.", "1", "ԱԲԳԴԵ", None])
def test_malformed_title_letters_are_refused(letter):
    with pytest.raises(mz.OpError, match="section title 1: the letter"):
        mz.materialize_page(mz.baseline_lines(SEG), [], [{"letter": letter, "box": [10, 10, 50, 50]}])


@pytest.mark.parametrize("box", [None, [10, 10, 50], [50, 10, 10, 50], [10, 10, 50, "x"]])
def test_malformed_title_boxes_are_refused(box):
    with pytest.raises(mz.OpError, match="section title 1: the box"):
        mz.materialize_page(mz.baseline_lines(SEG), [], [{"letter": "Ա", "box": box}])


# --- refused ops -------------------------------------------------------------------------


@pytest.mark.parametrize("op, message", [
    ({"op": "reshape", "line": "line_001", "boundary": [[0, 0], [10, 10]]}, "at least 3 points"),
    ({"op": "reshape", "line": "line_001", "boundary": [[0, 0], [10, 10], [10, 0], [0, 10]]},
     "not valid"),
    ({"op": "split", "line": "line_001", "cut": [[500, 90]]}, "at least 2 points"),
    ({"op": "initial", "box": [1, 2, 3], "line": "line_001"}, r"\[x1, y1, x2, y2\]"),
    ({"op": "initial", "box": [90, 140, 910, 260], "line": "line_001"}, "covers all of 'line_002'"),
    ({"op": "page_number", "line": "line_001", "value": " "}, "needs a value"),
    ({"op": "page_number", "value": "454"}, "a line or a box"),
    ({"op": "break"}, "needs a y"),
    ({"op": "dismiss_ink", "box": [1, 2]}, r"\[x1, y1, x2, y2\]"),
    ({"op": "rotate"}, "unknown op"),
])
def test_malformed_ops_are_refused(op, message):
    with pytest.raises(mz.OpError, match=message):
        run([op])


# --- reading order -------------------------------------------------------------------------


def test_page_where_most_lines_cross_the_middle_has_no_gutter():
    lines = lines_of(*[(f"l{i}", [100, 100 * i, 1900, 100 * i + 50]) for i in range(1, 5)],
                     ("x", [100, 600, 900, 650]), ("y", [1100, 600, 1900, 650]))
    assert mz.find_gutter(lines) is None


def test_empty_page_materializes_to_no_lines():
    assert mz.materialize_page([], []) == {"lines": [], "page_number": None}


def test_initial_box_sharing_no_rows_with_its_line_is_refused():
    with pytest.raises(mz.OpError, match="doesn't touch 'line_002' or share any of its rows"):
        run([{"op": "initial", "box": [40, 160, 95, 190], "line": "line_002"}])


def test_box_that_would_cut_another_line_in_two_is_refused():
    # a tall box through the middle of line_002, joined to line_001 above it
    with pytest.raises(mz.OpError, match="cut 'line_002' in two"):
        run([{"op": "grow", "box": [400, 120, 500, 260], "line": "line_001"}])


def test_legacy_grow_op_still_materializes():
    lines = run([{"op": "grow", "box": [80, 100, 99, 150], "line": "line_001"}])
    assert lines[0]["bbox"][0] == 80


# --- fixes from the PR #3 review -----------------------------------------------------------


def split_at(x: float) -> dict:
    return {"op": "split", "line": "line_001", "cut": [[x, 90], [x, 160]]}


def test_a_split_key_from_a_different_cut_gets_a_new_id():
    first = mz.mint_ids(500, run([split_at(500)]), mz.empty_id_state())
    halves = {first["ids"]["line_001/1"], first["ids"]["line_001/2"]}
    same = mz.mint_ids(500, run([split_at(500)]), first)
    assert same["ids"] == first["ids"]  # re-verified unchanged: same ids
    moved = mz.mint_ids(500, run([split_at(800)]), first)
    assert not halves & {moved["ids"]["line_001/1"], moved["ids"]["line_001/2"]}
    assert set(moved["retired"]) >= halves
    assert moved["retired"][first["ids"]["line_001/1"]]["superseded_by"] == [moved["ids"]["line_001/1"]]
    assert moved["ids"]["line_002"] == first["ids"]["line_002"]  # other lines keep theirs


def test_a_retired_split_key_is_not_restored_from_a_different_cut():
    first = mz.mint_ids(500, run([split_at(500)]), mz.empty_id_state())
    halves = {first["ids"]["line_001/1"], first["ids"]["line_001/2"]}
    unsplit = mz.mint_ids(500, run([]), first)  # the halves retire
    resplit = mz.mint_ids(500, run([split_at(800)]), unsplit)
    assert not halves & {resplit["ids"]["line_001/1"], resplit["ids"]["line_001/2"]}
    back = mz.mint_ids(500, run([split_at(500)]), unsplit)  # the same cut does come back
    assert back["ids"]["line_001/1"] == first["ids"]["line_001/1"]


def test_ids_minted_before_cuts_were_recorded_are_kept():
    first = mz.mint_ids(500, run([split_at(500)]), mz.empty_id_state())
    legacy = {k: v for k, v in first.items() if k != "id_cuts"}
    again = mz.mint_ids(500, run([split_at(800)]), legacy)
    assert again["ids"]["line_001/1"] == first["ids"]["line_001/1"]


def test_initial_in_an_outline_notch_bridges_without_a_hull():
    # line_009 is an L: a top bar, and a lower part only from x=300. The box sits in the
    # notch under the bar, overlapping the line's bbox in x but touching neither part.
    ell = [[100, 100], [900, 100], [900, 200], [300, 200], [300, 160], [100, 160]]
    seg = {"page": 501, "lines": [{"id": "line_009", "boundary": ell, "baseline": [[100, 150], [900, 150]],
                                   "bbox": [100, 100, 900, 200], "source": "kraken-fill"}]}
    op = {"op": "initial", "box": [120, 175, 200, 198], "line": "line_009", "letter": "Ա"}
    [line] = mz.apply_ops(mz.baseline_lines(seg), [op])
    poly = Polygon(line["boundary"])
    assert poly.is_valid
    assert poly.contains(Point(160, 185)) and poly.contains(Point(250, 185))  # box + bridge
    assert not poly.contains(Point(160, 167))  # a hull would fill the notch above the box
    assert line["initial"] == "Ա"


def kraken_seg(boxes: dict[str, list[float]]) -> dict:
    return {"page": 502, "lines": [seg_line(k, b, source="kraken-fill") for k, b in boxes.items()]}


def test_merging_stacked_kraken_lines_gives_a_synthetic_baseline():
    seg = kraken_seg({"line_001": [100, 100, 900, 150], "line_002": [100, 150, 900, 200]})
    [line] = mz.apply_ops(mz.baseline_lines(seg), [{"op": "merge", "lines": ["line_001", "line_002"]}])
    assert line["baseline_source"] == "synthetic"
    assert len({y for _, y in line["baseline"]}) == 1


def test_merging_side_by_side_kraken_lines_keeps_one_baseline_in_the_box():
    seg = kraken_seg({"line_001": [100, 100, 480, 150], "line_002": [500, 100, 900, 150]})
    [line] = mz.apply_ops(mz.baseline_lines(seg), [{"op": "merge", "lines": ["line_001", "line_002"]}])
    assert line["baseline_source"] == "kraken"
    x1, y1, x2, y2 = line["bbox"]
    assert all(x1 <= x <= x2 and y1 <= y <= y2 for x, y in line["baseline"])


@pytest.mark.parametrize("letter", ["<img src=x onerror=alert(1)>", "A1", "ԱԲ"])
def test_an_initial_must_be_one_armenian_letter(letter):
    op = {"op": "initial", "box": [60, 100, 98, 150], "line": "line_001", "letter": letter}
    with pytest.raises(mz.OpError, match="one Armenian letter"):
        run([op])


def test_an_initial_without_a_letter_is_still_allowed():
    [first, *_] = run([{"op": "initial", "box": [60, 100, 98, 150], "line": "line_001", "letter": None}])
    assert "initial" not in first


@pytest.mark.parametrize("value", ["45<b>", "four", "12345"])
def test_a_page_number_must_be_digits(value):
    with pytest.raises(mz.OpError, match="1 to 4 digits"):
        run([{"op": "page_number", "box": [10, 10, 50, 40], "value": value}])


def test_dumps_writes_one_line_per_line_record():
    review = {"page": 500, "status": "verified", "ops": [], "verified_at": "2026-10-02T00:00:00+00:00",
              **mz.mint_ids(500, run([]), mz.empty_id_state())}
    record = mz.verified_record(SEG, review, baseline_sha256="abc")
    text = mz.dumps(record)
    assert json.loads(text) == record
    rows = text.splitlines()
    assert len(rows) == len(record) + 2 + len(record["lines"]) + 1  # braces, lines' brackets
    assert sum(r.startswith('  {"id": ') for r in rows) == len(record["lines"])
    assert mz.dumps({"page": 1, "lines": []}) == '{\n "page": 1,\n "lines": []\n}\n'
