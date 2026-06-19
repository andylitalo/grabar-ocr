"""
column_detector.py
Detect the two Classical Armenian text columns on a normal two-column page.

Strategy: vertical projection profile (foreground-pixel count per image column) on
a DESKEWED page. A two-column page shows two wide, dense plateaus (the columns)
separated by a deep central valley (the gutter) and bordered by low-density outer
margins. We:
  1. find the gutter as the deep valley in the central band,
  2. take each column's x-extent as the dominant contiguous high-density run on
     its side (isolated marginalia form separate short runs and are dropped),
  3. take each column's y-extent from the horizontal projection of that x-slice
     (trims running headers / footers / folio numbers).

Boxes are padded slightly OUTWARD so letters are never clipped — we err toward
including whitespace, never excluding ink. Boxes are returned in the same dict
format as ``labeling_ui.pipeline.default_columns`` so the existing crop pipeline
is reused unchanged.

Edge cases (single-column headers, full-page images, tables) are out of scope:
they are *flagged* via ``diagnostics["confident"] = False`` so callers defer them,
never silently mis-cropped.

Usage (debug):
    python -m data_prep.column_detector --image data/_labeling_work/page_0051/page_deskew.png
"""

from __future__ import annotations

import argparse
import json
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Central fraction of page width searched for the gutter valley.
_GUTTER_BAND = (0.40, 0.60)
# Gutter is valid only if its density is below this fraction of the typical
# in-column density (measured gutters run ~12-22% of column median).
_GUTTER_MAX_FRAC_OF_COL = 0.40
# A column's x/y body must span at least this fraction of its search dimension.
_MIN_RUN_FRAC = 0.50
# Two real columns have comparable width; flag if the narrower is below this
# fraction of the wider.
_MIN_WIDTH_RATIO = 0.70
# Each column's text band must cover at least this fraction of page height.
_MIN_HEIGHT_FRAC = 0.50
# Inter-line gaps in a column's horizontal projection (up to this fraction of
# height) are bridged so the comb of per-line runs becomes one body block. Larger
# gaps (running header / footer set off by extra space) stay separate and trim.
_BRIDGE_FRAC = 0.025
# A near-full-width dark row (this fraction of the column width is ink) is a
# decorative horizontal rule. These books bracket the text body with a top and a
# bottom rule; the body sits between them and the folio number above the top one.
_RULE_FRAC = 0.80
# Rules are looked for only within this fraction of page height from each edge,
# so a dense text row mid-column can never be mistaken for a rule.
_RULE_MARGIN_FRAC = 0.40
# Outward padding applied to every box edge (fraction of the relevant dimension).
_PAD_FRAC = 0.006


def _binarize(gray: np.ndarray) -> np.ndarray:
    _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


def _smooth(profile: np.ndarray, window: int) -> np.ndarray:
    """Hann-window moving average; window forced odd and >= 3."""
    window = max(3, window | 1)
    kern = np.hanning(window)
    kern /= kern.sum()
    return np.convolve(profile, kern, mode="same")


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs as [start, end) index pairs."""
    out: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def _bridge(runs: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    """Merge runs separated by a gap <= ``max_gap`` into single runs."""
    if not runs:
        return runs
    merged = [runs[0]]
    for s, e in runs[1:]:
        ps, pe = merged[-1]
        if s - pe <= max_gap:
            merged[-1] = (ps, e)
        else:
            merged.append((s, e))
    return merged


def _dominant_run(
    profile: np.ndarray, threshold: float, lo: int, hi: int, *, max_gap: int = 0
) -> tuple[int, int] | None:
    """Widest run above ``threshold`` within ``profile[lo:hi]`` (absolute idx).

    Runs separated by <= ``max_gap`` are bridged first, so a comb of per-line
    runs collapses into one body block while larger gaps stay split.
    """
    mask = profile[lo:hi] > threshold
    runs = _bridge(_runs(mask), max_gap)
    if not runs:
        return None
    s, e = max(runs, key=lambda r: r[1] - r[0])
    return lo + s, lo + e


def _detect_rules(
    binary_slice: np.ndarray, h: int
) -> tuple[int | None, int | None]:
    """Find the body-bracketing horizontal rules in a column's binary x-slice.

    Returns ``(body_top, body_bottom)``: the bottom edge of the lowest rule in the
    upper margin and the top edge of the highest rule in the lower margin, or
    ``None`` for either side when no rule is present there.
    """
    cw = binary_slice.shape[1]
    if cw == 0:
        return None, None
    frac = binary_slice.sum(axis=1).astype(np.float64) / 255.0 / cw
    groups = _runs(frac > _RULE_FRAC)
    margin = _RULE_MARGIN_FRAC * h
    top_edges = [e for s, e in groups if e < margin]
    bottom_starts = [s for s, e in groups if s > h - margin]
    body_top = max(top_edges) if top_edges else None
    body_bottom = min(bottom_starts) if bottom_starts else None
    return body_top, body_bottom


def _trim_margins(
    hp: np.ndarray, top: int, bottom: int, threshold: float, bridge: int
) -> tuple[int, int]:
    """Trim a cleanly-separated running header / footer from a column's y-span.

    Only a leading/trailing block that is a SINGLE short run (<= 1.5x the column's
    median line height) AND set off by a clear gap (>= 2x ``bridge``) is removed —
    e.g. an isolated folio number. Multi-line body blocks (even when split by an
    internal gap) are never trimmed, so body text cannot be clipped.
    """
    runs = [(s + top, e + top) for s, e in _runs(hp[top:bottom] > threshold)]
    if len(runs) < 3:
        return top, bottom
    med = float(np.median([e - s for s, e in runs]))
    blocks = _bridge(runs, bridge)
    if len(blocks) >= 2:
        first, nxt = blocks[0], blocks[1]
        if (first[1] - first[0]) <= 1.5 * med and (nxt[0] - first[1]) >= 2 * bridge:
            top = nxt[0]
        last, prev = blocks[-1], blocks[-2]
        if (last[1] - last[0]) <= 1.5 * med and (last[0] - prev[1]) >= 2 * bridge:
            bottom = prev[1]
    return top, bottom


def detect_columns(
    gray: np.ndarray,
    *,
    min_run_frac: float = _MIN_RUN_FRAC,
    smooth_frac: float = 0.01,
    pad_frac: float = _PAD_FRAC,
) -> tuple[list[dict], dict]:
    """Detect two columns on a deskewed grayscale page.

    Returns ``(boxes, diagnostics)``. ``boxes`` is a list of two dicts
    ``{"x1","y1","x2","y2"}`` (full-resolution pixels), or an empty list when not
    confident. ``diagnostics`` always carries ``confident`` (bool), ``reason``,
    ``gutter_x``, and the measured densities.
    """
    if gray.ndim != 2:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    binary = _binarize(gray)

    # Vertical projection: foreground pixels per image column.
    vp = binary.sum(axis=0).astype(np.float64) / 255.0
    vp = _smooth(vp, int(smooth_frac * w))
    vmax = float(vp.max())
    diag: dict = {"confident": False, "reason": "", "page_w": w, "page_h": h}
    if vmax <= 0:
        diag["reason"] = "blank page (no foreground)"
        return [], diag

    # Typical in-column density: median over the dense (text) columns.
    col_median = float(np.median(vp[vp > 0.20 * vmax]))
    diag["col_median"] = col_median

    # Gutter = deepest valley in the central band.
    lo_b, hi_b = int(_GUTTER_BAND[0] * w), int(_GUTTER_BAND[1] * w)
    gutter_x = lo_b + int(np.argmin(vp[lo_b:hi_b]))
    gutter_val = float(vp[gutter_x])
    diag.update(gutter_x=gutter_x, gutter_val=gutter_val)
    if gutter_val > _GUTTER_MAX_FRAC_OF_COL * col_median:
        diag["reason"] = (
            f"no clear gutter (valley {gutter_val:.0f} vs col median {col_median:.0f})"
        )
        return [], diag

    # Per-column x-extent: dominant high-density run on each side of the gutter.
    x_thresh = max(0.05 * vmax, 0.20 * col_median)
    left = _dominant_run(vp, x_thresh, 0, gutter_x)
    right = _dominant_run(vp, x_thresh, gutter_x, w)
    if left is None or right is None:
        diag["reason"] = "missing column body on one side"
        return [], diag

    x_pad = max(1, round(pad_frac * w))
    y_pad = max(1, round(pad_frac * h))
    boxes: list[dict] = []
    widths: list[int] = []
    for side, (xs, xe) in enumerate((left, right)):
        # Pad outward but split exactly at the gutter (the minimum-ink column), so
        # the two boxes never overlap. This is the cut that crosses the least ink;
        # a straight vertical split can still graze a glyph that leans into the
        # gutter, but by no more than a stroke's width.
        x1 = gutter_x if side == 1 else max(0, xs - x_pad)
        x2 = gutter_x if side == 0 else min(w, xe + x_pad)
        widths.append(x2 - x1)

        # Per-column y-extent. The horizontal projection is a comb of per-line
        # runs; take the FULL span (first to last text row) so an internal gap
        # (section break, sparse line) can never clip body text.
        hp = binary[:, x1:x2].sum(axis=1).astype(np.float64) / 255.0
        hmax = float(hp.max())
        text_rows = np.where(hp > 0.05 * hmax)[0]
        if text_rows.size == 0:
            diag["reason"] = "no text band in a column"
            return [], diag
        top, bottom = int(text_rows[0]), int(text_rows[-1]) + 1

        # Prefer the decorative rules that bracket the body (excludes folio number
        # and the rules themselves); fall back to a conservative margin trim when a
        # rule is absent on a side.
        rule_top, rule_bottom = _detect_rules(binary[:, x1:x2], h)
        if rule_top is not None:
            y1 = rule_top
        else:
            top, _ = _trim_margins(hp, top, bottom, 0.05 * hmax, round(_BRIDGE_FRAC * h))
            y1 = max(0, top - y_pad)
        if rule_bottom is not None:
            y2 = rule_bottom
        else:
            _, bottom = _trim_margins(hp, top, bottom, 0.05 * hmax, round(_BRIDGE_FRAC * h))
            y2 = min(h, bottom + y_pad)
        boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})

    # Confidence checks for "normal two-column page".
    width_ratio = min(widths) / max(widths)
    diag["width_ratio"] = width_ratio
    if width_ratio < _MIN_WIDTH_RATIO:
        diag["reason"] = f"columns unequal (width ratio {width_ratio:.2f})"
        return [], diag
    for b in boxes:
        if (b["y2"] - b["y1"]) < _MIN_HEIGHT_FRAC * h:
            diag["reason"] = "a column's text band is too short (header/image page?)"
            return [], diag
    for (xs, xe), b in zip((left, right), boxes):
        if (xe - xs) < min_run_frac * (w / 2):
            diag["reason"] = "a column body is too narrow"
            return [], diag

    diag["confident"] = True
    return boxes, diag


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Detect two columns on a deskewed page")
    parser.add_argument("--image", required=True, help="Path to a deskewed page PNG")
    args = parser.parse_args()

    gray = cv2.imread(args.image, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(f"Cannot read image: {args.image}")
    boxes, diag = detect_columns(gray)
    print(json.dumps({"boxes": boxes, "diagnostics": diag}, indent=2))


if __name__ == "__main__":
    main()
