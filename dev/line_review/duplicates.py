"""Find lines Paddle boxed twice, so a fresh review starts with the copy deleted.

Paddle sometimes returns one printed line as two near-identical boxes (same text, a few
pixels apart). Drawn on top of each other, the second hides the first, and the page's
numbering looks like it skips (p.476: 85, 87 and 89 sat under their twins). Left in,
both copies are verified and the line is transcribed twice (pp.463, 474).

Two lines are copies when their boxes overlap with IoU >= 0.6. Across the whole
paddle-filled baseline every pair above 0.6 (20 pairs on 15 pages, 0.61-1.0) is the same
line read twice; a line inside a box merged over two lines scores about 0.5. The larger
box is kept, since it holds the most ink.
"""

from __future__ import annotations

MIN_IOU = 0.6


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


def auto_ops(lines: list[dict]) -> list[dict]:
    """A fresh review's ops: delete the smaller copy of each doubled line."""
    return [{"op": "delete", "line": drop, "auto": True} for _, drop in pairs(lines)]
