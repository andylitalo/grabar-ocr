"""Find initial capitals the lines miss, so a fresh review starts with them attached.

Most Phase 9 corrections were initials (29 of the first 53 edits): a capital at the start
of a line, taller than the line, that Paddle's box clips or leaves out entirely. Small
ones rise above the line; drop caps run down beside the next line or two.

The rule works on ink blobs (connected components of the black-and-white render):

- **A capital** is a blob 1.3-6 line heights tall and initial-sized (not speckle, not a
  column rule), plus its other pieces: Ա's two strokes, a drop cap's flag.
- **Its line** (``target_line``) is the topmost line whose middle is level with the
  capital and that starts right at it, never one further right (in the other column,
  which the reviewer UI's old rule could pick). The Initial tool's drawn boxes use the
  same rule (``target_for_box``). Paddle sometimes boxes the capital on
  its own; that box is not the line, and the caller deletes it (``absorbs``).
- **Detection** (``detect``) proposes a capital only where at least 10% of its box lies
  outside the lines. Scored against the reviewer's 29 initials on pp.453-463: all 29
  found; the 9 extra proposals there are real initials the line already mostly held.

Sizes are in units of the page's median line height. Lines are ``{"key", "bbox",
"boundary"}`` (``baseline_lines`` or materialized lines).
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

INK = 128                        # renders are already black/white
MIN_TALL, MAX_TALL = 1.3, 6.0    # text ascenders stay under ~1.2
MIN_WIDE, MAX_WIDE = 0.3, 3.0    # column rules are thinner, frames longer
MIN_ASPECT = 0.2                 # width / height: an Ի stem is ~0.26, a frame rule ~0.1
MIN_FILL = 0.15                  # ink / box area: an outline or bracket is emptier
PIECE_GAP = 0.3                  # pieces of one capital (Ա's two strokes) sit this close,
PIECE_GAP_TALL = 0.2             # or this share of its height for a drop cap's flag (p.463)
MIN_OUTSIDE = 0.10               # share of the capital's box outside every line
REACH = 1.5                      # its line starts within this distance right of it
OVERHANG = 0.3                   # ...and not further left of it than this
PAD = 3

Box = tuple[int, int, int, int]


class Page:
    """One page's ink blobs and lines, ready for capital lookups."""

    def __init__(self, image: np.ndarray, lines: list[dict]):
        import cv2
        self.image = image
        self.lines = [l for l in lines if len(l["boundary"]) >= 3]
        self.h = float(np.median([l["bbox"][3] - l["bbox"][1] for l in self.lines])) if self.lines else 50.0
        self.polys = {l["key"]: Polygon(l["boundary"]).buffer(0) for l in self.lines}
        self.covered = unary_union(list(self.polys.values()))
        _, _, stats, _ = cv2.connectedComponentsWithStats(
            (image < INK).astype(np.uint8), connectivity=8)
        self.blobs: dict[int, Box] = {i: (int(x), int(y), int(x + w), int(y + ht))
                                      for i, (x, y, w, ht, _) in enumerate(stats) if i}

    def _is_text(self, b: Box) -> bool:
        bb = box(*b)
        return bb.intersection(self.covered).area > 0.5 * bb.area

    def capital(self, seed: int) -> Box:
        """The seed blob grown over the capital's other pieces."""
        g = list(self.blobs[seed])
        grew = True
        while grew:
            grew = False
            for b in self.blobs.values():
                if b[0] >= g[0] and b[1] >= g[1] and b[2] <= g[2] and b[3] <= g[3]:
                    continue
                gap = max(b[0] - g[2], g[0] - b[2])
                rows = min(g[3], b[3]) - max(g[1], b[1])
                reach = max(PIECE_GAP * self.h, PIECE_GAP_TALL * (g[3] - g[1]))
                if gap > reach or rows < 0.5 * (b[3] - b[1]) or b[2] - b[0] < 3:
                    continue
                tall = b[3] - b[1] >= 0.7 * (g[3] - g[1])
                within = b[1] >= g[1] - 3 and b[3] <= g[3] + 3
                if tall or (within and not self._is_text(b)):
                    g = [min(g[0], b[0]), min(g[1], b[1]), max(g[2], b[2]), max(g[3], b[3])]
                    grew = True
        return tuple(g)

    def is_capital(self, g: Box) -> bool:
        x1, y1, x2, y2 = g
        h = self.h
        if not (MIN_TALL * h <= y2 - y1 <= MAX_TALL * h and MIN_WIDE * h <= x2 - x1 <= MAX_WIDE * h):
            return False
        if (x2 - x1) < MIN_ASPECT * (y2 - y1):
            return False
        return (self.image[y1:y2, x1:x2] < INK).mean() >= MIN_FILL

    def own_boxes(self, g: Box) -> list[dict]:
        """Lines that are just a box over the capital (Paddle boxed it on its own)."""
        region = box(*g).buffer(PAD)
        return [l for l in self.lines
                if box(*l["bbox"]).area and box(*l["bbox"]).intersection(region).area
                >= 0.7 * box(*l["bbox"]).area]

    def target_line(self, g: Box, own: list[dict] = ()) -> dict | None:
        """The line a capital starts: level with it and beginning at its right edge."""
        x1, y1, x2, y2 = g
        cands = [l for l in self.lines
                 if l not in own
                 and y1 <= (l["bbox"][1] + l["bbox"][3]) / 2 <= y2
                 and x1 - OVERHANG * self.h <= l["bbox"][0] <= x2 + REACH * self.h]
        return min(cands, key=lambda l: l["bbox"][1]) if cands else None

    def proposal(self, g: Box) -> dict | None:
        own = self.own_boxes(g)
        line = self.target_line(g, own)
        if line is None:
            return None
        x1, y1, x2, y2 = g
        return {"box": [x1 - PAD, y1 - PAD, x2 + PAD, y2 + PAD], "line": line["key"],
                "absorbs": [l["key"] for l in own]}


def detect(image: np.ndarray, lines: list[dict]) -> list[dict]:
    """Proposed initials, top to bottom: ``{"box", "line", "absorbs"}``.

    ``absorbs`` are lines that are only a box over the capital; delete them before
    joining the initial to ``line``.
    """
    page = Page(image, lines)
    if not page.lines:
        return []
    h = page.h
    seeds = sorted((i for i, b in page.blobs.items()
                    if MIN_TALL * h <= b[3] - b[1] <= MAX_TALL * h
                    and MIN_WIDE * h <= b[2] - b[0] <= MAX_WIDE * h),
                   key=lambda i: page.blobs[i][1] - page.blobs[i][3])  # tallest first
    found, done = [], []
    for seed in seeds:
        b = page.blobs[seed]
        if any(d[0] <= b[0] and d[1] <= b[1] and d[2] >= b[2] and d[3] >= b[3] for d in done):
            continue
        g = page.capital(seed)
        done.append(g)
        if not page.is_capital(g):
            continue
        own = page.own_boxes(g)
        rest = unary_union([page.polys[l["key"]] for l in page.lines if l not in own])
        gb = box(*g)
        if gb.difference(rest).area / gb.area < MIN_OUTSIDE:
            continue
        p = page.proposal(g)
        if p:
            found.append(p)
    found.sort(key=lambda f: (f["box"][1], f["box"][0]))
    return found


def target_for_box(lines: list[dict], b: list[float]) -> dict:
    """Where a hand-drawn initial box goes: ``{"line": KEY | None, "absorbs": [KEY, ...]}``.

    ``absorbs`` are lines the box covers (a Paddle box over the capital alone): they're
    deleted first, since an initial can't be carved out of a line it swallows whole.
    """
    lines = [l for l in lines if len(l["boundary"]) >= 3]
    if not lines:
        return {"line": None, "absorbs": []}
    page = Page.__new__(Page)  # geometry only: no image needed
    page.lines = lines
    page.h = float(np.median([l["bbox"][3] - l["bbox"][1] for l in lines]))
    own = page.own_boxes(tuple(b))
    line = page.target_line(tuple(b), own)
    return {"line": line["key"] if line else None, "absorbs": [l["key"] for l in own]}


def auto_ops(image: np.ndarray, lines: list[dict]) -> list[dict]:
    """A fresh review's initial ops: delete Paddle's capital-only boxes, then join."""
    ops = []
    for p in detect(image, lines):
        ops += [{"op": "delete", "line": k, "auto": True} for k in p["absorbs"]]
        ops.append({"op": "initial", "box": p["box"], "line": p["line"], "auto": True})
    return ops
