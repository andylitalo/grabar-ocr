"""Lines whose crop shows another line's letters, to point the reviewer at them.

Boxes often overlap in the blank gap between lines, which costs a crop nothing. What
costs it is ink: a neighbour's descender or capital inside the box shows up in the crop,
where OCR reads it as part of this line. So a line is flagged when its crop holds at
least ``MIN_PX`` px of letters that belong to another line. The threshold is the one the
unclip re-verify of pp.453-516 was checked at (28 lines -> 10, all Paddle's own boxes;
docs/phase_9_line_segmentation_review.md).

- **Whose letter:** ``unclip``'s ownership rule (a box holds most of the blob, or is the
  only box touching it). A letter split between boxes, dust and rules belong to no line
  and are never counted.
- **In the crop:** the polygon mask ``crops.line_crop`` whitens with (PIL fill, edge
  pixels included), so the count is exactly the foreign ink the crop shows.

A warning for review, not a check that blocks verifying: some of these boxes are fine as
they are.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw

from . import storage, unclip

MIN_PX = 10

log = logging.getLogger(__name__)


def _crop_mask(boundary: list[list[float]], shape: tuple[int, int]) -> tuple[tuple[slice, slice], np.ndarray]:
    """The pixels ``crops.line_crop`` keeps for this boundary, inside its bounds."""
    xs, ys = [p[0] for p in boundary], [p[1] for p in boundary]
    x1, y1 = max(0, math.floor(min(xs))), max(0, math.floor(min(ys)))
    x2, y2 = min(shape[1], math.ceil(max(xs)) + 1), min(shape[0], math.ceil(max(ys)) + 1)
    if x2 <= x1 or y2 <= y1:
        return (slice(0, 0), slice(0, 0)), np.zeros((0, 0), bool)
    img = Image.new("L", (x2 - x1, y2 - y1), 0)
    ImageDraw.Draw(img).polygon([(x - x1, y - y1) for x, y in boundary], fill=1)
    return (slice(y1, y2), slice(x1, x2)), np.asarray(img, bool)


def foreign_ink(lines: list[dict], gray: np.ndarray) -> list[dict]:
    """``[{line, other, px, pixels, spots}]``: line key ``line``'s crop shows ``px`` px of
    line ``other``'s letters, at ``pixels`` ([[x, y], ...]); ``spots`` is the extent
    [x1, y1, x2, y2] of each letter's part, so the UI can ring it (a few px of a letter's
    tip are hard to see at page scale). Only pairs of ``MIN_PX`` or more, in line order."""
    if not lines:
        return []
    polys = [unclip._shape(l["boundary"]) for l in lines]
    page = unclip._Page(polys, gray)
    owner = np.full(page.n, -1)
    for j, p in enumerate(polys):
        owner[page.owned(j, unclip._height(p))] = j
    out = []
    for i, l in enumerate(lines):
        (sy, sx), m = _crop_mask(l["boundary"], gray.shape)
        lab = np.where(m, page.lab[sy, sx], 0)
        by_other: dict[int, list] = {}
        for c in np.unique(lab):
            j = owner[c] if c else -1
            if j < 0 or j == i:
                continue
            ys, xs = np.nonzero(lab == c)
            by_other.setdefault(int(j), []).append(np.stack([xs + sx.start, ys + sy.start], 1))
        for j, parts in sorted(by_other.items()):
            pts = np.concatenate(parts)
            if len(pts) >= MIN_PX:
                spots = [[int(q[:, 0].min()), int(q[:, 1].min()), int(q[:, 0].max()), int(q[:, 1].max())]
                         for q in parts]
                out.append({"line": l["key"], "other": lines[j]["key"], "px": int(len(pts)),
                            "pixels": pts.tolist(), "spots": spots})
    return out


# --- per page, for the review app ------------------------------------------------------

# page -> (state key, flags): one entry per page, so it isn't bounded. The page's ink
# blobs aren't kept: a label image per page would be GBs, and they take ~10 ms to redo.
_flags: dict[int, tuple[tuple, list[dict]]] = {}


def _state_key(page: int, review: dict) -> tuple:
    path = storage.render_path(page)
    edits = json.dumps([review["ops"], review.get("section_titles", [])], sort_keys=True)
    return (hashlib.sha256(edits.encode()).hexdigest(), storage.baseline_sha256(page),
            path.stat().st_mtime_ns if path.exists() else None)


def page_flags(page: int, review: dict, lines: list[dict]) -> list[dict]:
    """``foreign_ink`` of the page as ``review`` leaves it (``lines``: its materialized
    lines); none without a page render. Cached until the edits or the render change."""
    key = _state_key(page, review)
    hit = _flags.get(page)
    if hit and hit[0] == key:
        return hit[1]
    path = storage.render_path(page)
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path.exists() else None
    flags = foreign_ink(lines, gray) if gray is not None else []
    _flags[page] = (key, flags)
    return flags


def flagged_counts() -> dict[int, int]:
    """Flagged lines per page, for the pages computed so far (``warm`` fills the rest)."""
    return {p: len({f["line"] for f in flags}) for p, (_, flags) in list(_flags.items())}


def warm() -> None:
    """Compute every page's flags once, so the page list can show them (the app runs this
    in a background thread at startup; about a minute, mostly the fresh pages' unclip)."""
    for page in storage.list_pages():
        try:
            review = storage.load_review(page)
            page_flags(page, review, storage.materialized(page, review))
        except Exception as e:  # a page that can't materialize shows its error when opened
            log.warning("p%d: foreign-ink flags not computed: %s", page, e)
