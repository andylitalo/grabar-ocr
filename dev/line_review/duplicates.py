"""Drop Paddle's junk boxes before anything else sees the baseline.

Two kinds, both dropped:

- **A box inside another line.** Paddle sometimes returns one printed line twice: the
  same text a few pixels apart, or a thin junk box or a speck inside the real line.
  Drawn together, one hides the other and the page's numbering seems to skip (p.476:
  85, 87 and 89 sat under their twins). Left in, the line is verified and transcribed
  twice (pp.463, 474). The test is how much of the smaller box lies inside the other
  (intersection / smaller area), not IoU: a speck inside a full line has IoU ~0.01
  (p.485's "է", 20 x 12 px). Across the whole paddle-filled baseline every pair at 0.47
  or more is junk or a copy; the closest real neighbours, a tall heading box over the
  next line, reach 0.42. The threshold is 0.5 and the larger box is kept.
- **A box smaller than one character**: under 0.75 line heights tall and 1.25 wide (the
  page's median line height). Over the baseline that is 10 boxes, all junk: specks, an
  ornament's pieces, the top of an initial boxed on its own. Short real lines that
  Paddle boxed too thin (~20 px tall) are wide, and stay; so do p.641's one-letter
  table cells (36 x 45, line height 45).

``materialize_page`` applies ``dedupe`` before the review's ops, so the review UI, the
verified output and the auto ops all start without them. A box is kept when an op
names it, and a pair is kept whole when an op deletes the larger box: the reviewer
already chose (p.473 deleted one copy by hand), and their ops must keep applying.
"""

from __future__ import annotations

import statistics

MIN_INSIDE = 0.5                   # share of the smaller box inside the other
CHAR_TALL, CHAR_WIDE = 0.75, 1.25  # a box under both, in line heights, is a speck


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inside(a, b) -> float:
    """Share of the smaller of boxes ``a`` and ``b`` that lies inside the other."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min(_area(a), _area(b))
    return ix * iy / small if small else 1.0


def pairs(lines: list[dict]) -> list[tuple[str, str]]:
    """``(keep, drop)`` keys for each line lying inside another. Lines have ``key``, ``bbox``."""
    found, dropped = [], set()
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            if a["key"] in dropped or b["key"] in dropped or inside(a["bbox"], b["bbox"]) < MIN_INSIDE:
                continue
            keep, drop = (a, b) if _area(a["bbox"]) >= _area(b["bbox"]) else (b, a)
            found.append((keep["key"], drop["key"]))
            dropped.add(drop["key"])
    return found


def outline_pairs(lines: list[dict]) -> list[tuple[str, str]]:
    """``pairs`` by the lines' outlines rather than their boxes, for edited lines: an
    initial's line has a tall box but an L-shaped outline that only meets the next line
    (p.492)."""
    from shapely.geometry import Polygon
    polys = {l["key"]: Polygon(l["boundary"]).buffer(0) for l in lines if len(l["boundary"]) >= 3}
    found = []
    for k, d in pairs(lines):
        a, b = polys.get(k), polys.get(d)
        if a is None or b is None or not b.area:
            continue
        if a.intersection(b).area / min(a.area, b.area) >= MIN_INSIDE:
            found.append((k, d))
    return found


def specks(lines: list[dict]) -> list[str]:
    """Keys of boxes smaller than one character."""
    if not lines:
        return []
    h = statistics.median(l["bbox"][3] - l["bbox"][1] for l in lines)
    return [l["key"] for l in lines
            if l["bbox"][3] - l["bbox"][1] < CHAR_TALL * h and l["bbox"][2] - l["bbox"][0] < CHAR_WIDE * h]


def referenced(ops: list[dict]) -> set[str]:
    """Line keys the ops name."""
    keys = set()
    for op in ops:
        if isinstance(op.get("line"), str):
            keys.add(op["line"])
        keys.update(k for k in op.get("lines") or [] if isinstance(k, str))
    return keys


def dedupe(lines: list[dict], ops: list[dict] = ()) -> list[dict]:
    """``lines`` without specks or the smaller box of each pair, except where ``ops`` chose."""
    named = referenced(ops)
    deleted = {op.get("line") for op in ops if op.get("op") == "delete"}
    drop = {d for k, d in pairs(lines) if d not in named and k not in deleted}
    drop |= {k for k in specks(lines) if k not in named}
    return [l for l in lines if l["key"] not in drop]
