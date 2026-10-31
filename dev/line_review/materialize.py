"""Baseline segmentation + ordered review ops -> final lines, and stable line ids.

Pure functions, no I/O. The baseline is one page of ``paddle-filled`` (immutable);
a review holds an ordered list of ops applied to it:

    {"op": "delete",  "line": KEY}
    {"op": "reshape", "line": KEY, "boundary": [[x, y], ...]}
    {"op": "add",     "key": "add_NNN", "boundary": [[x, y], ...]}
    {"op": "split",   "line": KEY, "cut": [[x, y], ...]}      # polyline across the line
    {"op": "merge",   "lines": [KEY, KEY, ...]}
    {"op": "initial", "box": [x1, y1, x2, y2], "line": KEY, "letter": "Ա"}
    {"op": "grow",    "box": [x1, y1, x2, y2], "line": KEY}   # legacy: an initial with no letter
    {"op": "page_number", "line": KEY | "box": [x1, y1, x2, y2], "value": "454"}
    {"op": "break",   "y": Y}                                  # the gutter is interrupted here
    {"op": "order",   "lines": [KEY, ...]}                     # full permutation
    {"op": "dismiss_ink", "box": [x1, y1, x2, y2]}             # no geometry effect

Keys: baseline lines keep their ``line_NNN`` id; split halves are ``KEY/1``, ``KEY/2``
(left-to-right for a vertical cut, top-to-bottom for a horizontal one); a merge is
``KEY+KEY``; added lines carry the key the UI gave them. Later ops may reference
any of these.

Reading order: unless the review has an ``order`` op, the final lines are put in
column-first order (``reading_order``): find the gutter; anything that interrupts it
divides the page into bands, and each band reads its left column top to bottom, then its
right one. Interruptions are lines that cross the gutter, section-title boxes that sit
on it (a taregir letter under an ornament, p.564), and ``break`` ops for anything else.
Boxes sharing a row (a drop cap and its line, a title in pieces) read left to right.
The baseline's own order (Paddle's X-Y cut) cut the page horizontally first wherever
the columns' gaps lined up (p.460).

Before the ops, a line Paddle boxed twice loses its smaller copy, and boxes smaller than a
character go (``duplicates``), unless an op names them.

A page number is a page element, not text: the op takes its line out of the lines (and
the reading order) and records ``{value, box}`` for the page. Initial letters stay on
their line as ``initial``.

Line ids (``p<page>.<NNN>``) are minted from the materialized lines at verification
(``mint_ids``) and never reused; see the design section of the Phase 9 doc. Split keys
(``KEY/1``) and merges of them name a piece, not a cut, so each line also carries the
``cuts`` that made it: a key that comes back from a different cut gets a new id.
"""

from __future__ import annotations

import json
import re

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box as shapely_box
from shapely.ops import split as shapely_split, unary_union

from dev.lineseg_survey.ensemble import insert_in_order

from . import duplicates


class OpError(ValueError):
    """A review op that can't be applied to the current lines."""


# --- geometry helpers -------------------------------------------------------------


def _bbox(points: list[list[float]]) -> list[float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _synthetic_baseline(bbox: list[float]) -> list[list[float]]:
    """Same stand-in the survey runners use: a line ¾ of the way down the box."""
    x1, y1, x2, y2 = bbox
    y = y1 + 0.75 * (y2 - y1)
    return [[x1, y], [x2, y]]


def _polygon(points: list[list[float]], ctx: str) -> Polygon:
    if len(points) < 3:
        raise OpError(f"{ctx}: polygon needs at least 3 points")
    poly = Polygon(points)
    if not poly.is_valid or poly.area == 0:
        raise OpError(f"{ctx}: polygon is not valid (self-intersecting or empty)")
    return poly


def _points(poly: Polygon) -> list[list[float]]:
    coords = list(poly.exterior.coords)[:-1]  # drop the closing repeat
    return [[round(x, 2), round(y, 2)] for x, y in coords]


def _single(geom, ctx: str) -> Polygon:
    """One polygon from a union/difference: the hull of disjoint parts."""
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return geom.convex_hull
    raise OpError(f"{ctx}: geometry collapsed")


def _line(key: str, points: list[list[float]], *, baseline=None, baseline_source="synthetic",
          source: str, derived_from: list[str], lineage: list[str],
          cuts: list | None = None) -> dict:
    bbox = _bbox(points)
    cuts = cuts or []
    if baseline is None:
        baseline, baseline_source = _synthetic_baseline(bbox), "synthetic"
    return {"key": key, "boundary": points, "baseline": baseline,
            "baseline_source": baseline_source, "bbox": bbox, "source": source,
            "derived_from": derived_from, "lineage": lineage, "cuts": cuts}


def _clip_baseline(baseline: list[list[float]], bbox: list[float]) -> list[list[float]] | None:
    """``baseline`` cut to the x-range of ``bbox`` (unchanged if it already fits), or None
    if nothing is left or what's left leaves the box vertically."""
    x1, y1, x2, y2 = bbox
    if all(x1 <= x <= x2 for x, _ in baseline):
        clipped = baseline
    else:
        geom = LineString(baseline).intersection(shapely_box(x1, -1e9, x2, 1e9))
        if isinstance(geom, MultiLineString):
            geom = max(geom.geoms, key=lambda g: g.length)
        if not isinstance(geom, LineString) or geom.length == 0:
            return None
        clipped = [[round(x, 2), round(y, 2)] for x, y in geom.coords]
    return clipped if all(y1 <= y <= y2 for _, y in clipped) else None


def _with_boundary(line: dict, points: list[list[float]]) -> dict:
    """``line`` with a new polygon. A kraken baseline survives, cut to the new box's
    x-range, while it still lies inside the box vertically; otherwise it becomes
    synthetic."""
    bbox = _bbox(points)
    out = {**line, "boundary": points, "bbox": bbox}
    clipped = _clip_baseline(line["baseline"], bbox) if line["baseline_source"] == "kraken" else None
    if clipped is None:
        out["baseline"], out["baseline_source"] = _synthetic_baseline(bbox), "synthetic"
    else:
        out["baseline"] = clipped
    return out


# --- baseline ---------------------------------------------------------------------


def baseline_lines(seg: dict) -> list[dict]:
    """The baseline page's lines as materializer lines, in reading order."""
    out = []
    for l in seg["lines"]:
        source = l.get("source", "hyocr-paddle")
        out.append({
            "key": l["id"], "boundary": l["boundary"], "baseline": l["baseline"],
            "baseline_source": "kraken" if source == "kraken-fill" else "synthetic",
            "bbox": list(l["bbox"]), "source": source,
            "derived_from": [l["id"]], "lineage": [], "cuts": [],
        })
    return out


# --- ops --------------------------------------------------------------------------


def _index(lines: list[dict], key, ctx: str) -> int:
    for i, l in enumerate(lines):
        if l["key"] == key:
            return i
    raise OpError(f"{ctx}: no line {key!r}")


def _insert(lines: list[dict], line: dict) -> None:
    lines.insert(insert_in_order(lines, line), line)


def _split(lines: list[dict], op: dict, ctx: str) -> None:
    i = _index(lines, op.get("line"), ctx)
    line = lines.pop(i)
    cut = op.get("cut") or []
    if len(cut) < 2:
        raise OpError(f"{ctx}: cut needs at least 2 points")
    pieces = list(shapely_split(_polygon(line["boundary"], ctx), LineString(cut)).geoms)
    if len(pieces) != 2:
        raise OpError(f"{ctx}: cut must cross {line['key']!r} once, into 2 pieces "
                      f"(got {len(pieces)})")
    (cx1, cy1), (cx2, cy2) = cut[0], cut[-1]
    vertical = abs(cx2 - cx1) < abs(cy2 - cy1)
    pieces.sort(key=lambda p: p.centroid.x if vertical else p.centroid.y)
    for n, piece in enumerate(pieces, start=1):
        new = _line(f"{line['key']}/{n}", _points(piece), source=line["source"],
                    derived_from=line["derived_from"], lineage=line["lineage"] + [line["key"]],
                    cuts=line.get("cuts", []) + [[line["key"], cut]])
        if n == 1 and "initial" in line:  # the drop cap opens the line
            new["initial"] = line["initial"]
        _insert(lines, new)


def _merged_polygon(lines: list[dict], idx: list[int], ctx: str) -> Polygon:
    """One polygon for the lines at ``idx``.

    Touching members are just their union. Members with a gap between them are joined
    by their convex hull minus every other line in it, so the merge never takes in
    another line's ink. It is refused if other lines cut across the gap (alone or
    together), or if one lies wholly inside the merge.
    """
    members = unary_union([_polygon(lines[i]["boundary"], ctx) for i in idx])
    if isinstance(members, Polygon):
        return members
    hull = members.convex_hull
    others = [l for i, l in enumerate(lines) if i not in idx]
    blockers = [l for l in others if hull.intersection(_polygon(l["boundary"], ctx)).area > 0]
    if not blockers:
        return _single(hull, ctx)
    filled = hull.difference(unary_union([_polygon(l["boundary"], ctx) for l in blockers]))
    filled = filled.union(members)  # a member keeps any overlap it already had
    parts = list(filled.geoms) if hasattr(filled, "geoms") else [filled]
    parts = [p for p in parts if isinstance(p, Polygon) and p.intersection(members).area > 0]
    names = ", ".join(repr(l["key"]) for l in blockers)
    if len(parts) != 1:
        raise OpError(f"{ctx}: can't merge across {names}, which cut(s) between the lines")
    if parts[0].interiors:
        raise OpError(f"{ctx}: can't merge around {names}, which would sit inside the merge")
    return parts[0]


def _side_by_side(members: list[dict]) -> bool:
    """True if the members sit on one row, each to the right of the one before, so their
    kraken baselines join into one line instead of zigzagging between rows."""
    row = sorted(members, key=lambda m: m["bbox"][0])
    return (all(_same_row(a, b) for a in row for b in row)
            and all(a["bbox"][2] <= b["bbox"][0] + SIDE_BY_SIDE_SLACK
                    for a, b in zip(row, row[1:])))


SIDE_BY_SIDE_SLACK = 10  # px two neighbours on a row may overlap and still read as one line


def _merge(lines: list[dict], op: dict, ctx: str) -> None:
    keys = op.get("lines") or []
    if len(keys) < 2 or len(set(keys)) != len(keys):
        raise OpError(f"{ctx}: merge needs at least 2 distinct lines")
    idx = sorted(_index(lines, k, ctx) for k in keys)
    members = [lines[i] for i in idx]
    points = _points(_merged_polygon(lines, idx, ctx))
    baseline, bsrc = None, "synthetic"
    if all(m["baseline_source"] == "kraken" for m in members) and _side_by_side(members):
        joined = sorted((p for m in members for p in m["baseline"]), key=lambda p: p[0])
        baseline = _clip_baseline(joined, _bbox(points))
        bsrc = "kraken" if baseline is not None else "synthetic"
    merged = _line("+".join(m["key"] for m in members), points, baseline=baseline,
                   baseline_source=bsrc, cuts=[c for m in members for c in m.get("cuts", [])],
                   source=members[0]["source"] if len({m["source"] for m in members}) == 1 else "human",
                   derived_from=[d for m in members for d in m["derived_from"]],
                   lineage=[k for m in members for k in m["lineage"] + [m["key"]]])
    letters = [m["initial"] for m in members if "initial" in m]
    if letters:
        merged["initial"] = letters[0]
    for i in reversed(idx):
        lines.pop(i)
    lines.insert(idx[0], merged)


def _initial(lines: list[dict], op: dict, ctx: str) -> None:
    """Union ``box`` into the target line and carve it out of every other line.

    If the box doesn't touch the target (a drop cap drawn with a small gap), the gap is
    bridged by a strip inside the rows they share, never by a hull, which could reach
    across the next line's text. Refused: a box sharing no rows with the target, and a box
    that would cut another line in two (the smaller piece's ink would belong to no line).

    ``grow`` is the same op without a letter. The UI no longer offers it (reshape covers
    missed ink); it stays so reviews that used it still materialize.
    """
    box = op.get("box") or []
    if len(box) != 4:
        raise OpError(f"{ctx}: box must be [x1, y1, x2, y2]")
    letter = str(op.get("letter") or "").strip()
    if op.get("op") == "initial" and letter and not INITIAL_LETTER.match(letter):
        raise OpError(f"{ctx}: an initial is one Armenian letter (got {letter!r})")
    t = _index(lines, op.get("line"), ctx)
    target = _polygon(lines[t]["boundary"], ctx)
    added = shapely_box(*box)
    if not target.intersects(added):
        tx1, ty1, tx2, ty2 = target.bounds
        bx1, by1, bx2, by2 = added.bounds
        y1, y2 = max(ty1, by1), min(ty2, by2)
        if y2 <= y1:
            raise OpError(f"{ctx}: the box doesn't touch {lines[t]['key']!r} or share any of "
                          "its rows; draw it beside the line")
        x1, x2 = sorted((min(tx2, bx2), max(tx1, bx1)))
        added = added.union(shapely_box(x1, y1, x2, y2))
        if not isinstance(target.union(added), Polygon):
            # The boxes overlap in x but the outlines don't touch (a box in an outline's
            # notch): bridge with the hull of the two outlines inside the shared rows.
            band = shapely_box(min(tx1, bx1), y1, max(tx2, bx2), y2)
            bridge = unary_union([target.intersection(band), added.intersection(band)])
            added = added.union(bridge.convex_hull.intersection(band))
    for i, line in enumerate(lines):
        poly = _polygon(line["boundary"], ctx)
        if i == t:
            grown = poly.union(added)
            if not isinstance(grown, Polygon):
                raise OpError(f"{ctx}: can't join the box to {line['key']!r}; draw it so it "
                              "touches the line")
            lines[i] = _with_boundary(line, _points(grown))
            if op.get("op") == "initial" and str(op.get("letter") or "").strip():
                lines[i]["initial"] = str(op["letter"]).strip()
        elif poly.intersection(added).area > 0:
            rest = poly.difference(added)
            if rest.is_empty:
                raise OpError(f"{ctx}: box covers all of {line['key']!r}")
            if isinstance(rest, MultiPolygon):
                raise OpError(f"{ctx}: the box would cut {line['key']!r} in two; draw it so it "
                              "only trims that line's end")
            lines[i] = _with_boundary(line, _points(rest))


# --- reading order --------------------------------------------------------------

GUTTER_MARGIN = 15     # px a line must reach past the gutter to count as crossing it
GUTTER_SPAN = (0.35, 0.65)  # where to look for the gutter, as a share of the text width
MAX_CROSSING = 0.25    # more lines than this crossing the best gutter = single column
MIN_PER_COLUMN = 2     # lines needed on each side of a gutter (no real page changes at 2 vs 3)


def _height(l: dict) -> float:
    return l["bbox"][3] - l["bbox"][1]


def _same_row(a: dict, b: dict) -> bool:
    overlap = min(a["bbox"][3], b["bbox"][3]) - max(a["bbox"][1], b["bbox"][1])
    return overlap >= 0.5 * min(_height(a), _height(b))


def _by_rows(lines: list[dict]) -> list[dict]:
    """Top to bottom; boxes sharing a row read left to right."""
    rows: list[list[dict]] = []
    for l in sorted(lines, key=lambda l: l["bbox"][1]):
        if rows and any(_same_row(l, m) for m in rows[-1]):
            rows[-1].append(l)
        else:
            rows.append([l])
    return [l for row in rows for l in sorted(row, key=lambda l: l["bbox"][0])]


def _crosses(l: dict, x: float) -> bool:
    return l["bbox"][0] < x - GUTTER_MARGIN and l["bbox"][2] > x + GUTTER_MARGIN


def find_gutter(lines: list[dict]) -> float | None:
    """x of the column gutter, or None for a single-column page."""
    if len(lines) < 2 * MIN_PER_COLUMN:
        return None
    x0 = min(l["bbox"][0] for l in lines)
    width = max(l["bbox"][2] for l in lines) - x0
    scores = []
    for x in range(int(x0 + GUTTER_SPAN[0] * width), int(x0 + GUTTER_SPAN[1] * width), 5):
        left = sum(l["bbox"][2] <= x + GUTTER_MARGIN for l in lines)
        right = sum(l["bbox"][0] >= x - GUTTER_MARGIN for l in lines)
        if left >= MIN_PER_COLUMN and right >= MIN_PER_COLUMN:
            scores.append((x, sum(_crosses(l, x) for l in lines)))
    if not scores:
        return None
    least = min(c for _, c in scores)
    if least > MAX_CROSSING * len(lines):
        return None
    # the middle of the first run of best x's, not its edge
    run = []
    for x, c in scores:
        if c == least:
            run.append(x)
        elif run:
            break
    return run[len(run) // 2]


def reading_order(lines: list[dict], dividers: list[list[float]] = ()) -> list[dict]:
    """Column-first reading order (see the module docstring).

    ``dividers`` are boxes that interrupt the gutter if they sit on it (section titles,
    and ``break`` ops as zero-height boxes spanning the page).
    """
    g = find_gutter(lines)
    if g is None:
        return _by_rows(lines)
    full = [l for l in lines if _crosses(l, g)]
    cols = [l for l in lines if not _crosses(l, g)]
    full += [l for l in cols if any(_same_row(l, f) for f in full)]  # e.g. "1." beside a title
    cols = [l for l in cols if l not in full]
    rows: list[list[dict]] = []
    for l in _by_rows(full):
        if rows and any(_same_row(l, m) for m in rows[-1]):
            rows[-1].append(l)
        else:
            rows.append([l])

    def mid(ls: list[dict]) -> float:
        return (min(l["bbox"][1] for l in ls) + max(l["bbox"][3] for l in ls)) / 2

    # (y, lines on that row): full-width rows carry lines, dividers carry none
    cuts = [(mid(row), row) for row in rows]
    cuts += [((d[1] + d[3]) / 2, []) for d in dividers if d[0] < g < d[2]]
    cuts.sort(key=lambda c: c[0])
    out: list[dict] = []
    top = float("-inf")
    for bottom, row in cuts + [(float("inf"), [])]:
        band = [l for l in cols if top <= mid([l]) < bottom]
        out += _by_rows([l for l in band if (l["bbox"][0] + l["bbox"][2]) / 2 < g])
        out += _by_rows([l for l in band if (l["bbox"][0] + l["bbox"][2]) / 2 >= g])
        out += row
        top = bottom
    return out


# A section title is a taregir letter: one to four Armenian letters (Ա-Ֆ, ա-և).
TITLE_LETTER = re.compile(r"^[\u0531-\u0556\u0561-\u0587]{1,4}$")
INITIAL_LETTER = re.compile(r"^[\u0531-\u0556\u0561-\u0587]$")  # a drop cap
PAGE_NUMBER = re.compile(r"^\d{1,4}$")  # printed in Arabic digits throughout the Տօնացոյց


def check_section_titles(titles: list[dict]) -> None:
    """Raise ``OpError`` unless every title has a valid ``letter`` and ``box``."""
    for n, t in enumerate(titles, start=1):
        ctx = f"section title {n}"
        letter, box = t.get("letter"), t.get("box")
        if not isinstance(letter, str) or not TITLE_LETTER.match(letter):
            raise OpError(f"{ctx}: the letter must be 1 to 4 Armenian letters, "
                          f"with no spaces or punctuation (got {letter!r})")
        if (not isinstance(box, list) or len(box) != 4
                or not all(isinstance(v, (int, float)) for v in box)
                or not (box[0] < box[2] and box[1] < box[3])):
            raise OpError(f"{ctx}: the box must be [x1, y1, x2, y2] with x1 < x2 and "
                          f"y1 < y2 (got {box!r})")


def apply_ops(lines: list[dict], ops: list[dict]) -> list[dict]:
    """Apply ``ops`` in order to ``lines`` (from ``baseline_lines``); returns new lines."""
    return materialize_page(lines, ops)["lines"]


def materialize_page(lines: list[dict], ops: list[dict],
                     section_titles: list[dict] = ()) -> dict:
    """Apply ``ops``; returns ``{"lines": [...], "page_number": {value, box} | None}``.

    ``section_titles`` (the review's) only matter for reading order: one sitting on the
    gutter interrupts it. Lines Paddle boxed twice, and specks, are dropped first
    (``duplicates.dedupe``).
    """
    check_section_titles(section_titles)
    lines = [dict(l) for l in duplicates.dedupe(lines, ops)]
    page_number = None
    for n, op in enumerate(ops, start=1):
        kind = op.get("op")
        ctx = f"op {n} ({kind})"
        if kind == "delete":
            lines.pop(_index(lines, op.get("line"), ctx))
        elif kind == "reshape":
            i = _index(lines, op.get("line"), ctx)
            lines[i] = _with_boundary(lines[i], _points(_polygon(op.get("boundary") or [], ctx)))
        elif kind == "add":
            key = op.get("key")
            if not key or any(l["key"] == key for l in lines):
                raise OpError(f"{ctx}: add needs a new, unique key (got {key!r})")
            points = _points(_polygon(op.get("boundary") or [], ctx))
            _insert(lines, _line(key, points, source="human", derived_from=[], lineage=[]))
        elif kind == "split":
            _split(lines, op, ctx)
        elif kind == "merge":
            _merge(lines, op, ctx)
        elif kind in ("initial", "grow"):  # same geometry; initial also records the letter
            _initial(lines, op, ctx)
        elif kind == "order":
            order = op.get("lines") or []
            if sorted(order) != sorted(l["key"] for l in lines) or len(set(order)) != len(order):
                raise OpError(f"{ctx}: order must list every current line exactly once")
            by_key = {l["key"]: l for l in lines}
            lines = [by_key[k] for k in order]
        elif kind == "page_number":
            value = str(op.get("value", "")).strip()
            if not value:
                raise OpError(f"{ctx}: page number needs a value")
            if not PAGE_NUMBER.match(value):
                raise OpError(f"{ctx}: a page number is 1 to 4 digits (got {value!r})")
            if page_number is not None:
                raise OpError(f"{ctx}: the page already has a page number")
            if op.get("line") is not None:
                box = lines.pop(_index(lines, op["line"], ctx))["bbox"]
            elif len(op.get("box") or []) == 4:
                box = list(op["box"])
            else:
                raise OpError(f"{ctx}: page number needs a line or a box")
            page_number = {"value": value, "box": box}
        elif kind == "break":
            if not isinstance(op.get("y"), (int, float)):
                raise OpError(f"{ctx}: break needs a y")
        elif kind == "dismiss_ink":
            if len(op.get("box") or []) != 4:
                raise OpError(f"{ctx}: box must be [x1, y1, x2, y2]")
        else:
            raise OpError(f"{ctx}: unknown op")
    if not any(op.get("op") == "order" for op in ops):
        dividers = [t["box"] for t in section_titles]
        dividers += [[float("-inf"), op["y"], float("inf"), op["y"]] for op in ops if op.get("op") == "break"]
        lines = reading_order(lines, dividers)
    return {"lines": lines, "page_number": page_number}


# --- stable line ids --------------------------------------------------------------


def empty_id_state() -> dict:
    """No ids minted yet. ``retired_keys`` remembers retired keys so a restored line
    (e.g. a deleted line brought back) gets its old id instead of a new one. ``id_cuts``
    records the split cuts behind each id of a split piece (see ``mint_ids``)."""
    return {"ids": {}, "retired": {}, "retired_keys": {}, "next_seq": 1, "id_cuts": {}}


def mint_ids(page: int, lines: list[dict], state: dict) -> dict:
    """New id state after verifying ``lines`` (materialized, in reading order).

    Live keys keep their ids; restored keys get their retired id back; new keys get
    the next unused number, in reading order. Ids whose key disappeared are retired
    with ``superseded_by`` = the ids of the lines derived from them (empty if deleted).

    A split piece's key names its place (``KEY/1``), not its cut, so an id is kept or
    restored only if the piece comes from the same cuts as when the id was minted;
    otherwise the key gets a new id and the old one is retired. (Reviews verified before
    ``id_cuts`` existed have no record, and keep their ids.)
    """
    old_ids = dict(state.get("ids", {}))
    retired = {k: dict(v) for k, v in state.get("retired", {}).items()}
    retired_keys = dict(state.get("retired_keys", {}))
    id_cuts = {k: v for k, v in state.get("id_cuts", {}).items()}
    seq = state.get("next_seq", 1)

    def same_cuts(lid: str, line: dict) -> bool:
        return lid not in id_cuts or id_cuts[lid] == line.get("cuts", [])

    ids: dict[str, str] = {}
    for line in lines:
        key = line["key"]
        if key in old_ids and same_cuts(old_ids[key], line):
            ids[key] = old_ids[key]
        elif key in retired_keys and same_cuts(retired_keys[key], line):
            ids[key] = retired_keys.pop(key)
            retired.pop(ids[key], None)
        else:
            ids[key] = f"p{page}.{seq:03d}"
            seq += 1
        if line.get("cuts"):
            id_cuts[ids[key]] = line["cuts"]

    for key, lid in old_ids.items():
        if ids.get(key) == lid:
            continue
        successors = [ids[l["key"]] for l in lines
                      if key in l["lineage"] or (l["key"] == key and ids[key] != lid)]
        retired[lid] = {"superseded_by": successors}
        retired_keys[key] = lid

    return {"ids": ids, "retired": retired, "retired_keys": retired_keys, "next_seq": seq,
            "id_cuts": id_cuts}


# --- verified output --------------------------------------------------------------


def verified_record(seg: dict, review: dict, *, baseline_sha256: str,
                    page_el: dict | None = None) -> dict:
    """The committed ``data/verified_lines/page_<N>.json`` record for a verified review.

    Deterministic: everything comes from the baseline and the review (including
    ``verified_at``), so re-materializing reproduces the file byte for byte. ``page_el``:
    the review's ``materialize_page`` result, if the caller already has it.
    """
    page = page_el if page_el is not None else materialize_page(
        baseline_lines(seg), review.get("ops", []), review.get("section_titles", []))
    lines = page["lines"]
    ids = review.get("ids", {})
    missing = [l["key"] for l in lines if l["key"] not in ids]
    if missing:
        raise OpError(f"page {seg['page']}: no id minted for {missing}")
    return {
        "page": seg["page"],
        "baseline": {"tool": seg.get("tool", "paddle-filled"), "sha256": baseline_sha256},
        "verified_at": review.get("verified_at"),
        "page_number": page["page_number"],
        "section_titles": [{"letter": t["letter"], "box": t["box"]}
                           for t in review.get("section_titles", [])],
        "lines": [
            {"id": ids[l["key"]], "order": n, "key": l["key"], "boundary": l["boundary"],
             "baseline": l["baseline"], "baseline_source": l["baseline_source"],
             "bbox": l["bbox"], "source": l["source"], "derived_from": l["derived_from"],
             "initial": l.get("initial")}
            for n, l in enumerate(lines, start=1)
        ],
        "retired": review.get("retired", {}),
    }


def dumps(record: dict) -> str:
    return json.dumps(record, indent=1, ensure_ascii=False) + "\n"
