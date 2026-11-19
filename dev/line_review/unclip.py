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
- **Specks.** A small blob in the gap between lines is not taken in: below the text and
  away from the line's letters, or as close to another line's letters (``_strays``).
- **Carving.** A cut letter's tip inside another line's box (a descender running into the
  line below) is cut out of that box, plus ``MARGIN`` px, as ``initial`` does for a drop
  cap; not within ``GUARD`` px of that box's own letters, never splitting it, and only
  when the letter's own box then takes the tip in (else it would be in neither box)
  (``_carves``).
- **Extension.** The box takes in each cut letter's bounding box plus ``MARGIN`` px, only
  over that letter's columns, never inside another line's (carved) box and never within ``GUARD``
  px of a blob that belongs to another line (or to none). A neighbour's capital often
  sticks out of its own box into the gap, right where a descender is extended. A hole
  the extension leaves is filled, unless it holds such a blob or part of another box.

The page's grey anti-aliased edge is 1 px wide, so a 2 px margin covers it plus rounding.
A larger margin cuts no more letters free and, before the guard, took in more of other
lines' letters. Boxes are snapped to the 0.1 px the review file stores (``GRID``) while
they're built, so a notch can't fold into an invalid polygon when saved. A decorated capital's swash that no box touches is not attached: it can't
be told apart from other stray marks reliably, and review catches it.
"""

from __future__ import annotations

import cv2
import numpy as np
from shapely import set_precision
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
GRID = 0.1         # px: boundaries are saved to 0.1 px, so polygons are snapped to it
SLIVER = 2.0       # px²: overlap that snapping can leave between neighbouring boxes
STRAY_AREA = 150   # px: a speck or a mark; a letter is about 400-1,200
STRAY_GAP = 3      # px from the line's nearest letter


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
    return [_ink_shape(page, c, GUARD) for c in np.unique(page.lab[y1:y2 + 1, x1:x2 + 1])
            if c and not (best[c] == i and not unowned[c])]


def _gaps(stats: np.ndarray, c: int, others: np.ndarray) -> np.ndarray:
    """Distance between blob ``c``'s bbox and each of ``others``' (0 = touching)."""
    x, y, w, h = stats[c][:4]
    X, Y, W, H = (stats[others, k] for k in range(4))
    return np.maximum.reduce([X - (x + w), x - (X + W), Y - (y + h), y - (Y + H),
                              np.zeros(len(others), int)])


def _strays(page: _Page, i: int, owned: np.ndarray, cut: np.ndarray) -> set[int]:
    """Cut blobs of line ``i`` that are specks in the gap between lines, not text.

    Only small blobs (``STRAY_AREA``) entirely outside the line's text band (its letters'
    median top to median bottom), and only when the line has 3+ letters to find the band:
    - **below the text** and at least ``STRAY_GAP`` px from the line's letters: Grabar has
      no marks under the line, and a descender is part of its letter's blob (p.464);
    - **at least as close to another line's letters** as to this line's (p.479).

    Above the text, a speck looks like an accent (՛ ՜), ՚ or ՟ by size, place and spacing,
    so it is taken in (p.497). A blob touching a letter (a broken tip) is never a speck.
    """
    letters = np.nonzero(owned & (page.area >= STRAY_AREA))[0]
    small = [c for c in np.nonzero(cut)[0] if page.area[c] < STRAY_AREA]
    if len(letters) < 3 or not small:
        return set()
    top = np.median(page.stats[letters, cv2.CC_STAT_TOP])
    bottom = np.median(page.stats[letters, cv2.CC_STAT_TOP] + page.stats[letters, cv2.CC_STAT_HEIGHT])
    best = page.counts.argmax(axis=0)
    inked = (page.counts.max(axis=0) > 0) & (page.area >= 2 * MIN_AREA)
    own_ink = np.nonzero(owned & (page.area >= 2 * MIN_AREA))[0]
    other_ink = np.nonzero(inked & (best != i))[0]
    out = set()
    for c in small:
        y, h = page.stats[c][cv2.CC_STAT_TOP], page.stats[c][cv2.CC_STAT_HEIGHT]
        below, above = y >= bottom, y + h <= top
        if not (below or above):
            continue
        mine = own_ink[own_ink != c]
        g_own = _gaps(page.stats, c, mine).min() if len(mine) else 10 ** 6
        g_other = _gaps(page.stats, c, other_ink).min() if len(other_ink) else 10 ** 6
        if (below and g_own >= STRAY_GAP) or (g_own >= 1 and g_other <= g_own):
            out.add(int(c))
    return out


def _points(poly: Polygon) -> list[list[float]]:
    return [[round(x, 1), round(y, 1)] for x, y in poly.exterior.coords[:-1]]


def _ink_shape(page: _Page, c: int, d: int):
    """Blob ``c``'s ink, dilated by ``d`` px, as a polygon."""
    x, y, w, h = (int(v) for v in page.stats[c][:4])
    m = (page.lab[y:y + h, x:x + w] == c).astype(np.uint8)
    m = cv2.copyMakeBorder(m, d, d, d, d, cv2.BORDER_CONSTANT, value=0)
    if d:
        m = cv2.dilate(m, np.ones((2 * d + 1, 2 * d + 1), np.uint8))
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return unary_union([Polygon(cc[:, 0, :] + [x - d, y - d]).buffer(0.5)
                        for cc in contours if len(cc) >= 3])


def _snapped(g) -> Polygon | None:
    """``g`` on the ``GRID`` the review file stores, if it is still one valid polygon
    without holes there (rounding a pixel-staircase notch can fold it otherwise)."""
    g = set_precision(g.simplify(GRID), GRID)
    if g.geom_type != "Polygon" or g.interiors or not g.is_valid or g.is_empty:
        return None
    return g


def _carves(page: _Page, polys: list[Polygon],
            cuts: dict[int, list[int]]) -> tuple[list[Polygon], set[int]]:
    """Each box with the tips of other lines' cut letters carved out of it, and the lines
    whose tips were carved.

    A letter's tip often lies inside the next line's box (a descender running into the
    line below). The tip, plus ``MARGIN`` px, is cut out of that box, as ``initial`` does
    for a drop cap. Not when it would come within ``GUARD`` px of that box's own letters
    (or ink no box owns), or split the box: then the box stays and the tip stays cut.
    """
    best = page.counts.argmax(axis=0)
    unowned = page.counts.max(axis=0) == 0
    carved = list(polys)
    carvers: set[int] = set()
    for j, pj in enumerate(polys):
        cuts_j, from_j = [], set()
        for i, cs in cuts.items():
            if i == j:
                continue
            for c in cs:
                x, y, w, h = (int(v) for v in page.stats[c][:4])
                if not pj.intersects(shapely_box(x - MARGIN, y - MARGIN, x + w + MARGIN, y + h + MARGIN)):
                    continue
                tip = _ink_shape(page, c, MARGIN).intersection(pj)
                if tip.area < 1:
                    continue
                x1, y1, x2, y2 = (int(v) for v in tip.bounds)
                y1, x1 = max(y1 - GUARD - 1, 0), max(x1 - GUARD - 1, 0)
                near = [d for d in np.unique(page.lab[y1:y2 + GUARD + 2, x1:x2 + GUARD + 2])
                        if d and d != c and (best[d] == j or unowned[d])]
                if any(_ink_shape(page, d, GUARD).intersects(tip) for d in near):
                    continue
                cuts_j.append(tip)
                from_j.add(i)
        if not cuts_j:
            continue
        g = _snapped(pj.difference(unary_union(cuts_j)))
        if g is not None and g.area > 0.5 * pj.area:
            carved[j] = g
            carvers |= from_j
    return carved, carvers


def _extended(page: _Page, polys: list[Polygon], base: list[Polygon],
              cuts: dict[int, list[int]]) -> list[Polygon]:
    """Each box (``base``: after carving) grown over its cut letters; a box whose
    extension is refused is left as the very ``base`` object."""
    final = list(base)
    for i, cs in cuts.items():
        boxes = []
        for c in cs:
            x, y, w, h = (int(v) for v in page.stats[c][:4])
            boxes.append(shapely_box(x - MARGIN, y - MARGIN, x + w - 1 + MARGIN, y + h - 1 + MARGIN))
        add = unary_union(boxes)
        others = [p for j, p in enumerate(base) if j != i]
        add = add.difference(unary_union(others + _keep_out(page, i, add)))
        grown = unary_union([base[i], add])
        if grown.geom_type != "Polygon":   # a piece cut off by the guard: drop it
            grown = max(grown.geoms, key=lambda g: g.intersection(base[i]).area)
        # No simplifying here: it cut corners into a carved neighbour's notch. _snapped
        # keeps the vertex count down.
        if grown.geom_type != "Polygon":
            continue
        # A hole would be a gap in the line: fill it, unless it holds what the guard kept
        # out (another line's letter, or a box's notch closed off by the extension).
        filled = Polygon(grown.exterior)
        if grown.interiors:
            holes = filled.difference(grown)
            if any(holes.intersection(g).area > SLIVER
                   for g in others + _keep_out(page, i, holes)):
                continue
        grown = _snapped(filled)
        if grown is None:
            continue
        # A box may already overlap a neighbour; what it gains must not, beyond the
        # slivers that snapping to GRID leaves (under 2 px², below what a crop resolves).
        extra = grown.difference(polys[i])
        if any(extra.intersection(o).area > SLIVER for o in others):
            continue
        final[i] = grown
    return final


def unclipped(lines: list[dict], gray: np.ndarray) -> dict[str, list[list[float]]]:
    """``{line key: new boundary}`` for the lines whose box cuts one of their letters, and
    for the boxes a neighbour's letter was carved out of."""
    polys = [_shape(l["boundary"]) for l in lines]
    if not polys:
        return {}
    page = _Page(polys, gray, inset=INSET)
    cuts: dict[int, list[int]] = {}
    for i in range(len(lines)):
        owned = page.owned(i, _height(polys[i]))
        cut = owned & (page.area - page.inner[i] >= MIN_CUT)
        if cut.any():
            strays = _strays(page, i, owned, cut)
            cs = [int(c) for c in np.nonzero(cut)[0] if c not in strays]
            if cs:
                cuts[i] = cs
    # Tips are carved only for lines whose box then takes them in: a carve for a line whose
    # extension is refused would leave the tip in neither box (p.628 line_044 lost 639 px²
    # for line_043, refused over a 3.5 px² sliver). Drop those lines from the carving and
    # redo it; the set only shrinks, so this ends, usually after one pass.
    allowed = set(cuts)
    while True:
        base, carvers = _carves(page, polys, {i: cuts[i] for i in allowed})
        final = _extended(page, polys, base, cuts)
        refused = {i for i in carvers if final[i] is base[i]}
        if not refused:
            break
        allowed -= refused
    out = {}
    for l, before, after in zip(lines, polys, final):
        if after is not before and before.symmetric_difference(after).area >= 1:
            out[l["key"]] = _points(after)
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
