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
