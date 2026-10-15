"""Drop lines Paddle boxed twice, before anything else sees the baseline.

Paddle sometimes returns one printed line as two boxes on top of each other: the same
text a few pixels apart, or a thin junk box inside the real one. Drawn together, one
hides the other and the page's numbering seems to skip (p.476: 85, 87 and 89 sat under
their twins). Left in, the line is verified and transcribed twice (pp.463, 474).

Lines in one column shouldn't overlap at all, so a low threshold does: two lines are
copies when their boxes overlap with IoU >= 0.2. Across the whole paddle-filled
baseline every pair at 0.25 or more is the same line twice (28 pairs on 21 pages); the closest
real neighbours, a tall heading touching the next line, reach 0.17. The larger box is
kept, since it holds the most ink.

``materialize_page`` applies ``dedupe`` before the review's ops, so the review UI, the
verified output and the auto ops all start from the deduplicated lines. A pair is left
alone when an op names the smaller copy or deletes the larger: the reviewer already
chose which copy stays (p.473 deleted one by hand), and their ops must keep applying.
"""

from __future__ import annotations

MIN_IOU = 0.2


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = _area(a) + _area(b) - inter
    return inter / union if union else 0.0


def pairs(lines: list[dict]) -> list[tuple[str, str]]:
    """``(keep, drop)`` keys for each line that copies another. Lines have ``key``, ``bbox``."""
    found, dropped = [], set()
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            if a["key"] in dropped or b["key"] in dropped or iou(a["bbox"], b["bbox"]) < MIN_IOU:
                continue
            keep, drop = (a, b) if _area(a["bbox"]) >= _area(b["bbox"]) else (b, a)
            found.append((keep["key"], drop["key"]))
            dropped.add(drop["key"])
    return found


def referenced(ops: list[dict]) -> set[str]:
    """Line keys the ops name."""
    keys = set()
    for op in ops:
        if isinstance(op.get("line"), str):
            keys.add(op["line"])
        keys.update(k for k in op.get("lines") or [] if isinstance(k, str))
    return keys


def dedupe(lines: list[dict], ops: list[dict] = ()) -> list[dict]:
    """``lines`` without the smaller copy of each doubled line.

    A pair is kept whole when an op names the smaller copy, or deletes the larger one:
    the reviewer chose which copy stays.
    """
    named = referenced(ops)
    deleted = {op.get("line") for op in ops if op.get("op") == "delete"}
    drop = {d for k, d in pairs(lines) if d not in named and k not in deleted}
    return [l for l in lines if l["key"] not in drop]
