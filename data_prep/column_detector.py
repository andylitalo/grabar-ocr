"""
column_detector.py
Detect the Classical Armenian text regions on a DESKEWED page (Phase 6).

``detect_regions`` replaces the rigid "two boxes per page" model with an ordered,
typed region list — ``header`` / ``single`` / ``left`` / ``right`` — so headings
and single-column bands are sliced in reading order instead of being force-split
or deferred. Image-level only (no OCR, no APIs — same envelope as line_filter):

  1. Strip the page frame. Near-full-height vertical rules near the L/R edges and
     near-full-width horizontal rules near the top/bottom bound the text-block
     *interior*; every projection runs on the interior only, so frame ink can
     never enter a region box (generalises the old top/bottom-rule logic to all
     four sides).
  2. Segment the interior into vertical bands separated by clear horizontal gaps.
  3. Per band, test the central vertical projection for a gutter: a gutter -> a
     two-column band (``left`` + ``right``, inner edges set at the column body
     extents so a central divider rule and the gutter are excluded); no gutter ->
     a single-column band (``header`` when its median line height >= ~1.5x the page
     body median, else ``single``).
  4. Within each column the x-extent is the dominant contiguous high-density run,
     so isolated marginal note numbers (short runs set off by a gap) are dropped.

Boxes are bounded INWARD (never re-crossing the frame, divider, or each other) and
returned as ``{"order","type","x1","y1","x2","y2"}`` in full-resolution pixels.
``detect_columns`` is kept as a thin back-compat wrapper returning the plain
two-column ``[left, right]`` boxes (used by ``labeling_ui.pipeline`` and
``validate_columns``). Genuinely ambiguous layouts are still deferred via
``diagnostics["confident"] = False``.

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
# How far in from each page edge to look for a frame rule (fraction of the
# dimension). A frame sits in the outer margin; text never reaches this far out.
_FRAME_MARGIN_FRAC = 0.15
# Within a band, horizontal whitespace gaps up to this fraction of interior height
# are inter-line gaps (bridged into one band); larger gaps separate bands (e.g. a
# heading set off above the columns). Calibrate in the Phase 6 gate (Commit 4).
_BAND_GAP_FRAC = 0.030
# A single-column band is a header when its median line height is at least this
# multiple of the page body's median line height (Q2; calibrate in Commit 4).
_HEADER_HEIGHT_MULT = 1.5
# A band must cover at least this fraction of interior height to anchor the page
# body line-height reference (so a one-line heading never sets the reference).
_BODY_BAND_MIN_FRAC = 0.20


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


def _detect_frame(binary: np.ndarray) -> tuple[int, int, int, int]:
    """Find the rectangular page frame; return the text-block interior (ix1,iy1,ix2,iy2).

    A frame side is a near-solid rule in the outer margin: a vertical column (near
    the L/R edge) or horizontal row (near the top/bottom edge) whose ink fraction
    over the full opposite dimension exceeds ``_RULE_FRAC``. Text columns/rows never
    reach that fraction, so they are not mistaken for the frame. The interior is the
    region strictly inside whichever sides are present (full extent when a side has
    no frame).
    """
    h, w = binary.shape
    col_frac = binary.sum(axis=0).astype(np.float64) / 255.0 / h
    row_frac = binary.sum(axis=1).astype(np.float64) / 255.0 / w
    mx, my = int(_FRAME_MARGIN_FRAC * w), int(_FRAME_MARGIN_FRAC * h)

    left = [x for x in range(0, mx) if col_frac[x] > _RULE_FRAC]
    right = [x for x in range(max(0, w - mx), w) if col_frac[x] > _RULE_FRAC]
    top = [y for y in range(0, my) if row_frac[y] > _RULE_FRAC]
    bottom = [y for y in range(max(0, h - my), h) if row_frac[y] > _RULE_FRAC]

    ix1 = max(left) + 1 if left else 0
    ix2 = min(right) if right else w
    iy1 = max(top) + 1 if top else 0
    iy2 = min(bottom) if bottom else h
    if ix2 - ix1 < 0.3 * w or iy2 - iy1 < 0.3 * h:
        return 0, 0, w, h  # implausible (rule mis-fire) — keep the whole page
    return ix1, iy1, ix2, iy2


def _segment_bands(interior: np.ndarray) -> list[tuple[int, int]]:
    """Vertical text bands [top, bottom) within the interior, in reading order.

    The horizontal projection (ink per row) is a comb of per-line runs; gaps up to
    ``_BAND_GAP_FRAC`` of interior height are inter-line gaps (bridged into one
    band), larger gaps separate bands (a heading set off above the columns).
    """
    h = interior.shape[0]
    hp = interior.sum(axis=1).astype(np.float64) / 255.0
    hmax = float(hp.max())
    if hmax <= 0:
        return []
    runs = _runs(hp > 0.05 * hmax)
    return _bridge(runs, round(_BAND_GAP_FRAC * h))


def _median_line_height(band_bin: np.ndarray) -> float:
    """Median per-line run height in a band's binary x-slice (0 if no lines)."""
    h = band_bin.shape[0]
    hp = band_bin.sum(axis=1).astype(np.float64) / 255.0
    hmax = float(hp.max())
    if hmax <= 0:
        return 0.0
    runs = _runs(hp > 0.05 * hmax)
    return float(np.median([e - s for s, e in runs])) if runs else 0.0


def _band_split(
    band_bin: np.ndarray, smooth_frac: float
) -> tuple[str, list[tuple[int, int]], dict]:
    """Classify a band as two-column or single, returning its column x-extents.

    Returns ``(kind, x_extents, info)`` where ``kind`` is "two" (x_extents =
    [(ls,le),(rs,re)] body extents on each side of the gutter, divider/gutter
    excluded) or "single" (x_extents = [(s,e)] dominant body run, marginalia
    dropped) or "none" (no body). Coordinates are band-local (interior x).
    """
    w = band_bin.shape[1]
    vp = band_bin.sum(axis=0).astype(np.float64) / 255.0
    vp = _smooth(vp, int(smooth_frac * w))
    vmax = float(vp.max())
    info: dict = {}
    if vmax <= 0:
        return "none", [], info
    col_median = float(np.median(vp[vp > 0.20 * vmax]))
    x_thresh = max(0.05 * vmax, 0.20 * col_median)

    lo_b, hi_b = int(_GUTTER_BAND[0] * w), int(_GUTTER_BAND[1] * w)
    gutter_x = lo_b + int(np.argmin(vp[lo_b:hi_b])) if hi_b > lo_b else w // 2
    gutter_val = float(vp[gutter_x])
    info.update(gutter_x=gutter_x, gutter_val=gutter_val, col_median=col_median)

    gap = round(_BRIDGE_FRAC * w)
    if gutter_val <= _GUTTER_MAX_FRAC_OF_COL * col_median:
        left = _dominant_run(vp, x_thresh, 0, gutter_x, max_gap=gap)
        right = _dominant_run(vp, x_thresh, gutter_x, w, max_gap=gap)
        if left and right:
            return "two", [left, right], info
    body = _dominant_run(vp, x_thresh, 0, w, max_gap=gap)
    if body is None:
        return "none", [], info
    return "single", [body], info


def detect_regions(
    gray: np.ndarray, *, smooth_frac: float = 0.01, pad_frac: float = _PAD_FRAC
) -> tuple[list[dict], dict]:
    """Detect ordered, typed text regions on a deskewed grayscale page.

    Returns ``(regions, diagnostics)``. Each region is
    ``{"order","type","x1","y1","x2","y2"}`` in full-resolution pixels, ordered
    top-to-bottom (``left`` before ``right`` within a two-column band; a header /
    single band before the band that follows). ``type`` in
    {header, single, left, right}. ``diagnostics`` carries ``confident`` (bool),
    ``reason``, the interior, and per-band info. An empty list with
    ``confident=False`` means defer.
    """
    if gray.ndim != 2:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    binary = _binarize(gray)
    diag: dict = {"confident": False, "reason": "", "page_w": w, "page_h": h}
    if int(binary.sum()) == 0:
        diag["reason"] = "blank page (no foreground)"
        return [], diag

    ix1, iy1, ix2, iy2 = _detect_frame(binary)
    diag["interior"] = {"x1": ix1, "y1": iy1, "x2": ix2, "y2": iy2}
    interior = binary[iy1:iy2, ix1:ix2]
    iw = ix2 - ix1
    x_pad = max(1, round(pad_frac * w))
    y_pad = max(1, round(pad_frac * h))

    bands = _segment_bands(interior)
    if not bands:
        diag["reason"] = "no text band in interior"
        return [], diag

    # First pass: classify each band and record its body line height.
    parsed: list[dict] = []
    for bt, bb in bands:
        band_bin = interior[bt:bb, :]
        kind, extents, info = _band_split(band_bin, smooth_frac)
        if kind == "none":
            continue
        # line height measured over the band's body x-extent(s)
        xs = min(e[0] for e in extents)
        xe = max(e[1] for e in extents)
        lh = _median_line_height(band_bin[:, xs:xe])
        parsed.append({"top": bt, "bottom": bb, "kind": kind, "extents": extents,
                       "line_height": lh, "info": info})
    if not parsed:
        diag["reason"] = "no column body found in any band"
        return [], diag

    # Page body line-height reference: the median line height of the tallest band
    # that spans enough of the interior to be body (never a one-line heading).
    body_bands = [p for p in parsed if (p["bottom"] - p["top"]) >= _BODY_BAND_MIN_FRAC * (iy2 - iy1)]
    ref_pool = body_bands or parsed
    ref_lh = float(np.median([p["line_height"] for p in ref_pool if p["line_height"] > 0]) or 0.0)
    diag["body_line_height"] = ref_lh

    # Second pass: emit ordered, typed regions in interior->full coords.
    regions: list[dict] = []
    n_two = 0
    for p in parsed:
        y1 = max(0, iy1 + p["top"] - y_pad)
        y2 = min(h, iy1 + p["bottom"] + y_pad)
        if p["kind"] == "two":
            n_two += 1
            diag.setdefault("gutter_x", ix1 + p["info"]["gutter_x"])
            (ls, le), (rs, re) = p["extents"]
            # Inner edges at the body extents (le, rs) exclude the gutter AND any
            # central divider rule in it; pad each edge but bound it inward — outer
            # edges never cross the frame (interior), inner edges never cross the
            # gutter midline (so neither box re-admits the divider).
            mid = ix1 + (le + rs) // 2
            left_box = {
                "type": "left",
                "x1": max(ix1, ix1 + ls - x_pad),
                "x2": min(mid, ix1 + le + x_pad),
                "y1": y1, "y2": y2,
            }
            right_box = {
                "type": "right",
                "x1": max(mid, ix1 + rs - x_pad),
                "x2": min(ix2, ix1 + re + x_pad),
                "y1": y1, "y2": y2,
            }
            regions.append(left_box)
            regions.append(right_box)
        else:  # single
            (s, e) = p["extents"][0]
            bx1 = max(ix1, ix1 + s - x_pad)
            bx2 = min(ix2, ix1 + e + x_pad)
            is_header = ref_lh > 0 and p["line_height"] >= _HEADER_HEIGHT_MULT * ref_lh
            regions.append({"type": "header" if is_header else "single",
                            "x1": bx1, "y1": y1, "x2": bx2, "y2": y2})

    for i, r in enumerate(regions, start=1):
        r["order"] = i
    diag["n_two_column_bands"] = n_two
    diag["n_regions"] = len(regions)

    # Confidence: defer only genuinely ambiguous layouts. A clean single-column
    # page (one single band, full body) is now confident, not deferred.
    if n_two == 0 and len(regions) == 1 and regions[0]["type"] in ("single", "header"):
        body_w = regions[0]["x2"] - regions[0]["x1"]
        if body_w < _MIN_RUN_FRAC * iw:
            diag["reason"] = "single band too narrow (image / table?)"
            return [], diag
    elif n_two >= 1:
        # require the two-column band(s) to have comparable column widths
        for p in parsed:
            if p["kind"] != "two":
                continue
            (ls, le), (rs, re) = p["extents"]
            wl, wr = le - ls, re - rs
            if min(wl, wr) < _MIN_WIDTH_RATIO * max(wl, wr):
                diag["reason"] = f"two-column band unbalanced ({wl} vs {wr})"
                return [], diag
    diag["confident"] = True
    return regions, diag


def detect_columns(
    gray: np.ndarray,
    *,
    min_run_frac: float = _MIN_RUN_FRAC,
    smooth_frac: float = 0.01,
    pad_frac: float = _PAD_FRAC,
) -> tuple[list[dict], dict]:
    """Back-compat: the plain two-column ``[left, right]`` boxes for a page.

    Thin wrapper over ``detect_regions`` for the existing two-column consumers
    (``labeling_ui.pipeline.suggested_columns``, ``validate_columns``). Confident
    only when the page is exactly one two-column band (``left`` + ``right``) with
    no header/single regions; any other layout (header pages, single-column,
    image/table) defers, exactly as before. Boxes are ``{"x1","y1","x2","y2"}``.
    """
    regions, diag = detect_regions(gray, smooth_frac=smooth_frac, pad_frac=pad_frac)
    if not diag.get("confident"):
        return [], diag
    types = [r["type"] for r in regions]
    if types != ["left", "right"]:
        diag["confident"] = False
        diag["reason"] = f"not a plain two-column page (regions={types})"
        return [], diag
    h = gray.shape[0]
    boxes = [{k: r[k] for k in ("x1", "y1", "x2", "y2")} for r in regions]
    for b in boxes:
        if (b["y2"] - b["y1"]) < _MIN_HEIGHT_FRAC * h:
            diag["confident"] = False
            diag["reason"] = "a column's text band is too short (header/image page?)"
            return [], diag
    widths = [b["x2"] - b["x1"] for b in boxes]
    for w_ in widths:
        if w_ < min_run_frac * (gray.shape[1] / 2):
            diag["confident"] = False
            diag["reason"] = "a column body is too narrow"
            return [], diag
    return boxes, diag


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Detect text regions on a deskewed page")
    parser.add_argument("--image", required=True, help="Path to a deskewed page PNG")
    parser.add_argument("--columns", action="store_true",
                        help="back-compat: print the plain two-column boxes instead of regions")
    args = parser.parse_args()

    gray = cv2.imread(args.image, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(f"Cannot read image: {args.image}")
    if args.columns:
        boxes, diag = detect_columns(gray)
        print(json.dumps({"boxes": boxes, "diagnostics": diag}, indent=2))
    else:
        regions, diag = detect_regions(gray)
        print(json.dumps({"regions": regions, "diagnostics": diag}, indent=2))


if __name__ == "__main__":
    main()
