"""Push line boxes out over the letters they cut, so a fresh review starts unclipped.

Paddle's boxes often run along the tips of descenders (ր ը զ ց ղ դ ք յ) or just under the
top of a capital. A line crop whitens everything outside the box, so a cut of even 1-3 px
can make ր read as ը, or ղ as դ. On pp.453-516 the baseline cut 2,257 letters in 1,082 of
4,708 lines, and the verified pages still cut about 2,000: by hand, review fixed about one
in ten (docs/phase_9_line_segmentation_review.md, 2026-11-17).

The rule works on the page's ink (Otsu threshold) split into connected blobs, which are
letters, or pieces of one:

- **Whose letter.** A line owns a blob when its box holds at least ``MIN_INSIDE`` of it
  and ``DOMINANCE`` times as much as any other box. It also owns a blob no other box
  touches, if it holds at least ``SOLE_MIN`` of it and the blob is at most ``SOLE_MAX_H``
  line heights tall (a capital standing well above its line, or a box Paddle put
  half a line too high). A taller blob is a drop cap beside two lines: attaching it is the
  reviewer's ``initial``, and taking it into one line raised that box above the line before
  it and changed the reading order (p.460). Blobs smaller than ``MIN_AREA`` px (dust) and
  taller than ``MAX_H`` line heights (rules) are skipped.
- **Cut.** An owned blob with at least ``MIN_CUT`` px within ``INSET`` px of the edge, or
  outside it.
- **Extension.** The box takes in each cut letter's bounding box plus ``MARGIN`` px, only
  over that letter's columns, never inside another line's box and never within ``GUARD``
  px of a blob that belongs to another line (or to none). A neighbour's capital often
  sticks out of its own box into the gap, right where a descender is extended.

The page's grey anti-aliased edge is 1 px wide, so a 2 px margin covers it plus rounding.
A larger margin cuts no more letters free and, before the guard, took in more of other
lines' letters. A decorated capital's swash that no box touches is not attached: it can't
be told apart from other stray marks reliably, and review catches it.
"""

from __future__ import annotations

import cv2
import numpy as np
from shapely.geometry import Polygon
from shapely.geometry import box as shapely_box
from shapely.ops import unary_union

MIN_INSIDE = 0.35
DOMINANCE = 2.0
SOLE_MIN = 0.10
SOLE_MAX_H = 1.5
MIN_AREA = 20
MAX_H = 3.0
MIN_CUT = 3
INSET = 2
MARGIN = 2
GUARD = 2


def _ink(gray: np.ndarray) -> np.ndarray:
    _, b = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


def _shape(boundary: list[list[float]]) -> Polygon:
    p = Polygon(boundary).buffer(0)
    return max(p.geoms, key=lambda g: g.area) if p.geom_type != "Polygon" else p


def _mask(poly, shape: tuple[int, int]) -> tuple[tuple[slice, slice], np.ndarray]:
    """The polygon rasterized inside its own bbox (a full-page mask per line is too slow).
    Shrinking a hand-reshaped box can split it in pieces, or leave nothing."""
    if poly.is_empty:
        return (slice(0, 0), slice(0, 0)), np.zeros((0, 0), bool)
    x1, y1, x2, y2 = poly.bounds
    x1, y1 = max(int(x1) - 1, 0), max(int(y1) - 1, 0)
    x2, y2 = min(int(x2) + 2, shape[1]), min(int(y2) + 2, shape[0])
    m = np.zeros((y2 - y1, x2 - x1), np.uint8)
    for part in getattr(poly, "geoms", [poly]):
        if part.geom_type == "Polygon" and not part.is_empty:
            pts = np.round(np.array(part.exterior.coords) - [x1, y1]).astype(np.int32)
            cv2.fillPoly(m, [pts], 1)
    return (slice(y1, y2), slice(x1, x2)), m.astype(bool)


class _Page:
    """The ink blobs of a page and how much of each lies in each line's box."""

    def __init__(self, polys: list[Polygon], gray: np.ndarray, inset: float = 0):
        self.n, self.lab, self.stats, _ = cv2.connectedComponentsWithStats(
            _ink(gray), connectivity=8)
        self.area = self.stats[:, cv2.CC_STAT_AREA]
        self.counts = self._counts(polys, gray.shape)
        self.inner = self._counts([p.buffer(-inset, join_style=2) for p in polys], gray.shape) \
            if inset else self.counts

    def _counts(self, polys: list[Polygon], shape) -> np.ndarray:
        rows = []
        for p in polys:
            sl, m = _mask(p, shape)
            rows.append(np.bincount(self.lab[sl][m], minlength=self.n))
        c = np.stack(rows) if rows else np.zeros((0, self.n), int)
        c[:, 0] = 0   # background
        return c

    def owned(self, i: int, height: float) -> np.ndarray:
        """Bool per blob: line ``i`` owns it."""
        own = self.counts[i]
        other = np.delete(self.counts, i, axis=0).max(axis=0) if len(self.counts) > 1 \
            else np.zeros(self.n, int)
        h = self.stats[:, cv2.CC_STAT_HEIGHT]
        letter = (own > 0) & (self.area >= MIN_AREA) & (h <= MAX_H * height)
        main = (own >= MIN_INSIDE * self.area) & (own >= DOMINANCE * other)
        sole = (other == 0) & (own >= SOLE_MIN * self.area) & (h <= SOLE_MAX_H * height)
        return letter & (main | sole)


def _height(poly: Polygon) -> float:
    return poly.bounds[3] - poly.bounds[1]


def _keep_out(page: _Page, i: int, window: Polygon) -> list:
    """Blobs in ``window`` that are not line ``i``'s (most of their ink in another box, or
    in none), dilated by GUARD."""
    x1, y1, x2, y2 = (int(v) for v in window.bounds)
    y1, x1 = max(y1, 0), max(x1, 0)
    best = page.counts.argmax(axis=0) if len(page.counts) else np.zeros(page.n, int)
    unowned = page.counts.max(axis=0) == 0 if len(page.counts) else np.ones(page.n, bool)
    shapes = []
    for c in np.unique(page.lab[y1:y2 + 1, x1:x2 + 1]):
        if c == 0 or (best[c] == i and not unowned[c]):
            continue
        x, y, w, h = (int(v) for v in page.stats[c][:4])
        m = (page.lab[y:y + h, x:x + w] == c).astype(np.uint8)
        m = cv2.copyMakeBorder(m, GUARD, GUARD, GUARD, GUARD, cv2.BORDER_CONSTANT, value=0)
        m = cv2.dilate(m, np.ones((2 * GUARD + 1, 2 * GUARD + 1), np.uint8))
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cc in contours:
            if len(cc) >= 3:
                shapes.append(Polygon(cc[:, 0, :] + [x - GUARD, y - GUARD]).buffer(0.5))
    return shapes


def _points(poly: Polygon) -> list[list[float]]:
    return [[round(x, 1), round(y, 1)] for x, y in poly.exterior.coords[:-1]]


def unclipped(lines: list[dict], gray: np.ndarray) -> dict[str, list[list[float]]]:
    """``{line key: new boundary}`` for the lines whose box cuts one of their letters."""
    polys = [_shape(l["boundary"]) for l in lines]
    if not polys:
        return {}
    page = _Page(polys, gray, inset=INSET)
    out = {}
    for i, l in enumerate(lines):
        cut = page.owned(i, _height(polys[i])) & (page.area - page.inner[i] >= MIN_CUT)
        if not cut.any():
            continue
        boxes = []
        for c in np.nonzero(cut)[0]:
            x, y, w, h = (int(v) for v in page.stats[c][:4])
            boxes.append(shapely_box(x - MARGIN, y - MARGIN, x + w - 1 + MARGIN, y + h - 1 + MARGIN))
        add = unary_union(boxes)
        others = [p for j, p in enumerate(polys) if j != i]
        add = add.difference(unary_union(others + _keep_out(page, i, add)))
        grown = unary_union([polys[i], add])
        if grown.geom_type != "Polygon":   # a piece cut off by the guard: drop it
            grown = max(grown.geoms, key=lambda g: g.intersection(polys[i]).area)
        grown = unary_union([grown.simplify(0.5), polys[i]])
        if grown.geom_type != "Polygon":
            continue
        grown = Polygon(grown.exterior)   # a hole would be a gap in the line: fill it
        extra = grown.difference(polys[i])   # a box may already overlap a neighbour
        if any(extra.intersection(o).area > 1e-6 for o in others):
            continue
        if grown.area - polys[i].area < 1:
            continue
        out[l["key"]] = _points(grown)
    return out


def auto_ops(lines: list[dict], gray: np.ndarray) -> list[dict]:
    """The reshape ops a fresh review starts with (``"auto": true``), in line order."""
    return [{"op": "reshape", "line": key, "boundary": boundary, "auto": True}
            for key, boundary in unclipped(lines, gray).items()]


def ink_outside(lines: list[dict], i: int, gray: np.ndarray) -> int:
    """Pixels of line ``i``'s own letters that fall outside its box (0 = nothing cut)."""
    polys = [_shape(l["boundary"]) for l in lines]
    page = _Page(polys, gray)
    owned = page.owned(i, _height(polys[i]))
    return int((page.area - page.counts[i])[owned].sum())
