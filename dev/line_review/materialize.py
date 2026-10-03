"""Baseline segmentation + ordered review ops -> final lines, and stable line ids.

Pure functions, no I/O. The baseline is one page of ``paddle-filled`` (immutable);
a review holds an ordered list of ops applied to it:

    {"op": "delete",  "line": KEY}
    {"op": "reshape", "line": KEY, "boundary": [[x, y], ...]}
    {"op": "add",     "key": "add_NNN", "boundary": [[x, y], ...]}
    {"op": "split",   "line": KEY, "cut": [[x, y], ...]}      # polyline across the line
    {"op": "merge",   "lines": [KEY, KEY, ...]}
    {"op": "initial", "box": [x1, y1, x2, y2], "line": KEY, "letter": "Ա"}
    {"op": "grow",    "box": [x1, y1, x2, y2], "line": KEY}   # take in missed ink
    {"op": "order",   "lines": [KEY, ...]}                     # full permutation
    {"op": "dismiss_ink", "box": [x1, y1, x2, y2]}             # no geometry effect

Keys: baseline lines keep their ``line_NNN`` id; split halves are ``KEY/1``, ``KEY/2``
(left-to-right for a vertical cut, top-to-bottom for a horizontal one); a merge is
``KEY+KEY``; added lines carry the key the UI gave them. Later ops may reference
any of these.

Line ids (``p<page>.<NNN>``) are minted from the materialized lines at verification
(``mint_ids``) and never reused; see the design section of the Phase 9 doc.
"""

from __future__ import annotations

import json

from shapely.geometry import LineString, MultiPolygon, Polygon, box as shapely_box
from shapely.ops import split as shapely_split, unary_union

from dev.lineseg_survey.ensemble import insert_in_order


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
          source: str, derived_from: list[str], lineage: list[str]) -> dict:
    bbox = _bbox(points)
    if baseline is None:
        baseline, baseline_source = _synthetic_baseline(bbox), "synthetic"
    return {"key": key, "boundary": points, "baseline": baseline,
            "baseline_source": baseline_source, "bbox": bbox, "source": source,
            "derived_from": derived_from, "lineage": lineage}


def _with_boundary(line: dict, points: list[list[float]]) -> dict:
    """``line`` with a new polygon. A kraken baseline survives while it still lies
    inside the new box vertically; otherwise the baseline becomes synthetic."""
    bbox = _bbox(points)
    keep = line["baseline_source"] == "kraken" and all(
        bbox[1] <= y <= bbox[3] for _, y in line["baseline"])
    out = {**line, "boundary": points, "bbox": bbox}
    if not keep:
        out["baseline"], out["baseline_source"] = _synthetic_baseline(bbox), "synthetic"
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
            "derived_from": [l["id"]], "lineage": [],
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
        _insert(lines, _line(f"{line['key']}/{n}", _points(piece), source=line["source"],
                             derived_from=line["derived_from"],
                             lineage=line["lineage"] + [line["key"]]))


def _merge(lines: list[dict], op: dict, ctx: str) -> None:
    keys = op.get("lines") or []
    if len(keys) < 2 or len(set(keys)) != len(keys):
        raise OpError(f"{ctx}: merge needs at least 2 distinct lines")
    idx = sorted(_index(lines, k, ctx) for k in keys)
    members = [lines[i] for i in idx]
    poly = _single(unary_union([_polygon(m["boundary"], ctx) for m in members]), ctx)
    points = _points(poly)
    baseline, bsrc = None, "synthetic"
    if all(m["baseline_source"] == "kraken" for m in members):
        baseline = sorted((p for m in members for p in m["baseline"]), key=lambda p: p[0])
        bsrc = "kraken"
    merged = _line("+".join(m["key"] for m in members), points, baseline=baseline,
                   baseline_source=bsrc,
                   source=members[0]["source"] if len({m["source"] for m in members}) == 1 else "human",
                   derived_from=[d for m in members for d in m["derived_from"]],
                   lineage=[k for m in members for k in m["lineage"] + [m["key"]]])
    for i in reversed(idx):
        lines.pop(i)
    lines.insert(idx[0], merged)


def _initial(lines: list[dict], op: dict, ctx: str) -> None:
    """Union ``box`` into the target line and carve it out of every other line.

    If the box doesn't touch the target (a drop cap drawn with a small gap), the gap is
    bridged by a strip inside the rows they share, never by a hull, which could reach
    across the next line's text.
    """
    box = op.get("box") or []
    if len(box) != 4:
        raise OpError(f"{ctx}: box must be [x1, y1, x2, y2]")
    t = _index(lines, op.get("line"), ctx)
    target = _polygon(lines[t]["boundary"], ctx)
    added = shapely_box(*box)
    if not target.intersects(added):
        tx1, ty1, tx2, ty2 = target.bounds
        bx1, by1, bx2, by2 = added.bounds
        y1, y2 = max(ty1, by1), min(ty2, by2)
        if y2 > y1:
            x1, x2 = sorted((min(tx2, bx2), max(tx1, bx1)))
            added = added.union(shapely_box(x1, y1, x2, y2))
    for i, line in enumerate(lines):
        poly = _polygon(line["boundary"], ctx)
        if i == t:
            lines[i] = _with_boundary(line, _points(_single(poly.union(added), ctx)))
        elif poly.intersection(added).area > 0:
            rest = poly.difference(added)
            if rest.is_empty:
                raise OpError(f"{ctx}: box covers all of {line['key']!r}")
            if isinstance(rest, MultiPolygon):
                rest = max(rest.geoms, key=lambda g: g.area)
            lines[i] = _with_boundary(line, _points(rest))


def apply_ops(lines: list[dict], ops: list[dict]) -> list[dict]:
    """Apply ``ops`` in order to ``lines`` (from ``baseline_lines``); returns new lines."""
    lines = [dict(l) for l in lines]
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
        elif kind == "dismiss_ink":
            if len(op.get("box") or []) != 4:
                raise OpError(f"{ctx}: box must be [x1, y1, x2, y2]")
        else:
            raise OpError(f"{ctx}: unknown op")
    return lines


# --- stable line ids --------------------------------------------------------------


def empty_id_state() -> dict:
    """No ids minted yet. ``retired_keys`` remembers retired keys so a restored line
    (e.g. a deleted line brought back) gets its old id instead of a new one."""
    return {"ids": {}, "retired": {}, "retired_keys": {}, "next_seq": 1}


def mint_ids(page: int, lines: list[dict], state: dict) -> dict:
    """New id state after verifying ``lines`` (materialized, in reading order).

    Live keys keep their ids; restored keys get their retired id back; new keys get
    the next unused number, in reading order. Ids whose key disappeared are retired
    with ``superseded_by`` = the ids of the lines derived from them (empty if deleted).
    """
    old_ids = dict(state.get("ids", {}))
    retired = {k: dict(v) for k, v in state.get("retired", {}).items()}
    retired_keys = dict(state.get("retired_keys", {}))
    seq = state.get("next_seq", 1)

    ids: dict[str, str] = {}
    for line in lines:
        key = line["key"]
        if key in old_ids:
            ids[key] = old_ids[key]
        elif key in retired_keys:
            ids[key] = retired_keys.pop(key)
            retired.pop(ids[key], None)
        else:
            ids[key] = f"p{page}.{seq:03d}"
            seq += 1

    for key, lid in old_ids.items():
        if key in ids:
            continue
        successors = [ids[l["key"]] for l in lines if key in l["lineage"]]
        retired[lid] = {"superseded_by": successors}
        retired_keys[key] = lid

    return {"ids": ids, "retired": retired, "retired_keys": retired_keys, "next_seq": seq}


# --- verified output --------------------------------------------------------------


def verified_record(seg: dict, review: dict, *, baseline_sha256: str) -> dict:
    """The committed ``data/verified_lines/page_<N>.json`` record for a verified review.

    Deterministic: everything comes from the baseline and the review (including
    ``verified_at``), so re-materializing reproduces the file byte for byte.
    """
    lines = apply_ops(baseline_lines(seg), review.get("ops", []))
    ids = review.get("ids", {})
    missing = [l["key"] for l in lines if l["key"] not in ids]
    if missing:
        raise OpError(f"page {seg['page']}: no id minted for {missing}")
    return {
        "page": seg["page"],
        "baseline": {"tool": seg.get("tool", "paddle-filled"), "sha256": baseline_sha256},
        "verified_at": review.get("verified_at"),
        "lines": [
            {"id": ids[l["key"]], "order": n, "key": l["key"], "boundary": l["boundary"],
             "baseline": l["baseline"], "baseline_source": l["baseline_source"],
             "bbox": l["bbox"], "source": l["source"], "derived_from": l["derived_from"]}
            for n, l in enumerate(lines, start=1)
        ],
        "retired": review.get("retired", {}),
    }


def dumps(record: dict) -> str:
    return json.dumps(record, indent=1, ensure_ascii=False) + "\n"
