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
# A near-full-width dark row (this fraction of the region/page width is ink) is a
# decorative horizontal rule. These books bracket the text body with a top and a
# bottom rule; the body sits between them and the folio number above the top one.
# 0.70 catches a rule spanning the text block (~0.78 of full page width) while
# staying well above any text row (~0.4); calibrated on the real gold pages.
_RULE_FRAC = 0.70
# After a frame side is found, push the interior this far past the rule so its
# anti-aliased edge pixels never leak into a column projection / box border.
_FRAME_INSET_FRAC = 0.004
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
# Two-column purity guard. A clean two-column gutter is whitespace broken only by
# short pokes (punctuation, ascenders): the longest contiguous ink run in it stays
# <= ~0.25x the body line height across the gold pages. A full-width band fused
# into the two-column region (a heading/footer with no separating whitespace gap,
# e.g. page_0640 ~9.8x) instead crosses the gutter with a long contiguous run.
# When the run exceeds this many line heights the page is NOT a clean two-column
# page and is DEFERRED for manual region annotation rather than mis-sliced — the
# error asymmetry favours deferral (a wrongly-deferred clean page costs one human
# annotation; a wrongly-sliced header page silently corrupts data). 0.6 sits well
# above the clean max (0.25) and far below the divergent case (9.8).
_GUTTER_PURITY_MAX_LH = 0.6
# A contiguous horizontal ink run covering at least this fraction of a box's width,
# sitting on its top/bottom edge, is a (possibly degraded/dashed) decorative rule
# left on the crop edge — trim the box inward past it. This catches rules that the
# AVERAGE-ink detector (_RULE_FRAC) misses because a dashed rule's mean ink is below
# 0.70 even though its longest contiguous run is high (page_0160 bottom rule: run
# 0.82). Real text never fills half a column width as one unbroken horizontal run,
# so clean edges are untouched. Mirrors validate_columns.EDGE_RULE_FRAC.
_EDGE_RULE_FRAC = 0.50
# A rule is thin: never pull an edge in by more than this fraction of box height
# (protects real text if the contiguous-run test ever fired on a dense line).
_EDGE_RULE_MAX_TRIM_FRAC = 0.04


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

    inset_x, inset_y = round(_FRAME_INSET_FRAC * w), round(_FRAME_INSET_FRAC * h)
    ix1 = max(left) + 1 + inset_x if left else 0
    ix2 = min(right) - inset_x if right else w
    iy1 = max(top) + 1 + inset_y if top else 0
    iy2 = min(bottom) - inset_y if bottom else h
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


def _gutter_run_frac(
    band_bin: np.ndarray, le: int, rs: int, gutter_x: int, line_height: float
) -> float:
    """Longest contiguous vertical ink run in a two-column band's gutter, in line heights.

    Used by the two-column purity guard. The gutter between two clean columns is
    whitespace broken only by short pokes (punctuation, ascenders). A full-width
    band fused into the region (a heading/footer with no separating whitespace gap)
    crosses the gutter, leaving a long contiguous run. A genuine central divider
    RULE is excluded first (full-height ink columns) — it is already pulled out of
    the boxes and is not a sign of divergence. Coordinates are interior-local x;
    returns 0 when there is no measurable gutter or line height.
    """
    bh, w = band_bin.shape
    if line_height <= 0 or bh <= 0:
        return 0.0
    if rs > le + 4:                       # a real gutter gap between the column bodies
        a, b = le, rs
    else:                                 # columns abut (gutter filled) — sample a strip
        hw = max(3, round(0.006 * w))
        a, b = max(0, gutter_x - hw), min(w, gutter_x + hw + 1)
    chan = band_bin[:, a:b].astype(np.float64) / 255.0
    if chan.shape[1] == 0:
        return 0.0
    keep = (chan.sum(axis=0) / bh) <= _RULE_FRAC   # drop full-height divider columns
    if not keep.any():
        return 0.0
    occ = (chan[:, keep].sum(axis=1) / int(keep.sum())) > 0.04
    longest = max((e - s for s, e in _runs(occ)), default=0)
    return longest / line_height


def _longest_run_frac(mask: np.ndarray) -> float:
    """Longest contiguous True fraction of a 1-D boolean mask."""
    best = run = 0
    for v in mask:
        run = run + 1 if v else 0
        best = max(best, run)
    return best / max(1, len(mask))


def _strip_edge_rule(
    binary: np.ndarray, x1: int, y1: int, x2: int, y2: int
) -> tuple[int, int]:
    """Pull a box's top/bottom edge inward past a contiguous-run rule sitting on it.

    A decorative rule left on a crop edge lights up most of the edge row as one
    contiguous run (``>= _EDGE_RULE_FRAC`` of the box width). Real text never does,
    so a clean edge is a no-op. Trimming is capped at ``_EDGE_RULE_MAX_TRIM_FRAC`` of
    the box height (a rule is thin) so dense text can never be eaten. Full-page
    coordinates; only ``y1``/``y2`` change.
    """
    h, w = binary.shape
    bw, bh = x2 - x1, y2 - y1
    if bw <= 0 or bh <= 0:
        return y1, y2
    cap = max(2, int(_EDGE_RULE_MAX_TRIM_FRAC * bh))
    yb = min(y2, h - 1)                      # clamp into the image before scanning rows
    trimmed_b = False
    for _ in range(cap):
        if yb > y1 and _longest_run_frac(binary[yb, x1:x2] > 0) >= _EDGE_RULE_FRAC:
            yb -= 1
            trimmed_b = True
        else:
            break
    new_y2 = yb if trimmed_b else y2         # keep original when no edge rule was found
    yt = max(y1, 0)
    trimmed_t = False
    for _ in range(cap):
        if yt < new_y2 and _longest_run_frac(binary[yt, x1:x2] > 0) >= _EDGE_RULE_FRAC:
            yt += 1
            trimmed_t = True
        else:
            break
    new_y1 = yt if trimmed_t else y1
    return (new_y1, new_y2) if new_y2 > new_y1 else (y1, y2)


def _trim_region_y(
    interior: np.ndarray, top: int, bottom: int, rx1: int, rx2: int
) -> tuple[int, int]:
    """Refine a region's [top, bottom) to the body, excluding folio / running header.

    Runs the body-bracketing rule detector and the isolated-folio trim (the old
    per-column logic) on the region's x-slice within the band, so a folio number or
    running header sitting above the text — but inside the frame — is dropped from
    the box. Coordinates are interior-local.
    """
    band = interior[top:bottom, rx1:rx2]
    bh = bottom - top
    if bh <= 0 or band.shape[1] <= 0:
        return top, bottom
    hp = band.sum(axis=1).astype(np.float64) / 255.0
    hmax = float(hp.max())
    if hmax <= 0:
        return top, bottom
    rows = np.where(hp > 0.05 * hmax)[0]
    t, b = int(rows[0]), int(rows[-1]) + 1
    rule_top, rule_bottom = _detect_rules(band, bh)
    bridge = round(_BRIDGE_FRAC * bh)
    if rule_top is not None:
        t = rule_top
    else:
        t, _ = _trim_margins(hp, t, b, 0.05 * hmax, bridge)
    if rule_bottom is not None:
        b = rule_bottom
    else:
        _, b = _trim_margins(hp, t, b, 0.05 * hmax, bridge)
    return top + t, top + b


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

    # Second pass: emit ordered, typed regions in interior->full coords. Each
    # region's y-extent is bracketed to the body (folio / running header trimmed)
    # over its own x-slice, then padded gently within the band + interior.
    regions: list[dict] = []
    n_two = 0
    gutter_runs: list[float] = []  # purity guard: longest gutter ink run per two-band

    def _y_bounds(top_i: int, bot_i: int) -> tuple[int, int]:
        # Pad outward to catch ascender/descender tips that sit above/below the
        # first/last dense row, bounded by the interior. Bands are separated by
        # gaps >> y_pad, so this never bleeds into an adjacent band.
        y1 = max(iy1, iy1 + top_i - y_pad)
        y2 = min(iy2, iy1 + bot_i + y_pad)
        return y1, y2

    for p in parsed:
        if p["kind"] == "two":
            n_two += 1
            if "gutter_x" not in diag:  # expose the first two-column band's gutter
                diag["gutter_x"] = ix1 + p["info"]["gutter_x"]
                diag["gutter_val"] = p["info"]["gutter_val"]
                diag["col_median"] = p["info"]["col_median"]
            (ls, le), (rs, re) = p["extents"]
            gutter_runs.append(_gutter_run_frac(
                interior[p["top"]:p["bottom"], :], le, rs, p["info"]["gutter_x"], ref_lh))
            lt, lb = _trim_region_y(interior, p["top"], p["bottom"], ls, le)
            rt, rb = _trim_region_y(interior, p["top"], p["bottom"], rs, re)
            ly1, ly2 = _y_bounds(lt, lb)
            ry1, ry2 = _y_bounds(rt, rb)
            # Inner edges: split at the gutter valley (the minimum-ink column → the
            # cut that crosses the least ink, so no glyph is clipped), UNLESS a
            # central divider rule sits in the gutter, in which case pull each inner
            # edge clear of it. A divider is a near-full-height ink column.
            left_inner = right_inner = ix1 + int(p["info"]["gutter_x"])
            if rs > le:
                strip = interior[p["top"]:p["bottom"], le:rs]
                bh = p["bottom"] - p["top"]
                gcol = strip.sum(axis=0).astype(np.float64) / 255.0 / max(1, bh)
                div = np.where(gcol > _RULE_FRAC)[0]
                if div.size:
                    left_inner = ix1 + le + int(div.min())
                    right_inner = ix1 + le + int(div.max()) + 1
            regions.append({"type": "left",
                            "x1": max(ix1, ix1 + ls - x_pad), "x2": left_inner,
                            "y1": ly1, "y2": ly2})
            regions.append({"type": "right",
                            "x1": right_inner, "x2": min(ix2, ix1 + re + x_pad),
                            "y1": ry1, "y2": ry2})
        else:  # single
            (s, e) = p["extents"][0]
            st, sb = _trim_region_y(interior, p["top"], p["bottom"], s, e)
            sy1, sy2 = _y_bounds(st, sb)
            is_header = ref_lh > 0 and p["line_height"] >= _HEADER_HEIGHT_MULT * ref_lh
            regions.append({"type": "header" if is_header else "single",
                            "x1": max(ix1, ix1 + s - x_pad), "x2": min(ix2, ix1 + e + x_pad),
                            "y1": sy1, "y2": sy2})

    # Final cleanup: trim any degraded/dashed rule left sitting on a box's top or
    # bottom edge (the average-ink rule detector misses these). No-op on clean edges.
    for r in regions:
        r["y1"], r["y2"] = _strip_edge_rule(binary, r["x1"], r["y1"], r["x2"], r["y2"])

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
        # Purity guard: a full-width band fused into a two-column region (a heading /
        # footer with no whitespace gap) crosses the gutter, so the page is not a
        # clean two-column page — defer it for manual annotation rather than mis-slice.
        worst_run = max(gutter_runs, default=0.0)
        diag["gutter_run_lh"] = round(worst_run, 2)
        if worst_run > _GUTTER_PURITY_MAX_LH:
            diag["reason"] = (f"full-width content crosses the column gutter "
                              f"(run {worst_run:.1f}× line height — fused header/footer?)")
            return [], diag
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
