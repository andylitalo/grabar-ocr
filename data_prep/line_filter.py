"""
line_filter.py
Image-level detection of non-character lines BEFORE OCR.

The line slicer occasionally emits crops that are not Grabar text: ornamental
section dividers (horizontal rules, heart-motif bands) and over-segmentation
artifacts (blank specks). TrOCR "reads" them into nonsense, which then pollutes
the concatenated LLM-correction prompt and the final digitized text.

Two filtering ideas were rejected with evidence (see the plan doc):
  - training TrOCR to emit nothing on these lines — expensive, risks real lines;
  - filtering on the Armenian-character count of the OCR *output* — useless: on
    page_0487_auto junk lines produce as many Armenian chars as real text.

The reliable signal is purely image-level and computed before OCR, reusing the
repo's connected-component glyph discriminator (``is_glyph``, shared with
data_prep.validate_columns so the two can never diverge). Measured envelope on
page_0487_auto:
  - real text:     glyph 5–41, ink ≈ 0.11–0.19  (≤ 1.15× the page-median ink)
  - horizontal rule / blank specks: glyph == 0
  - ornament band (heart motifs):   ink ≈ 2.2–2.4× the page-median
Trap avoided: a real short wrapped word (``մութիւն։``) had ink 0.054 — so a
*low-ink* rule would drop real lines. We never use one. Every junk line instead
sits OUTSIDE the text envelope on a side text never occupies: glyph_count == 0,
or ink far above the page median.

This module is intentionally lightweight — cv2 + numpy only, no pipeline /
storage / torch imports — so ml_vision/scripts/predict_lines.py can import it.
"""

from __future__ import annotations

import cv2
import numpy as np

# Default discriminator: a line is non-character when it has no glyph-like
# components at all (rules + specks) OR its ink is far above the page median
# (dense ornament bands). 1.6× sits well clear of the real-text max (≈1.15×) and
# below the junk min (≈2.2×); tune via the detect_nonchar_lines dry run.
DEFAULT_INK_FACTOR = 1.6


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Otsu threshold to a foreground=255 mask (mirrors column_detector._binarize)."""
    _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


def is_glyph(cw: int, ch: int, area: int, col_w: int, col_h: int) -> bool:
    """True if a connected component is plausibly a single glyph (not a rule/ornament/frame).

    This is the single source of truth shared with data_prep.validate_columns,
    which aliases this function so the two never diverge.
    """
    if area < 20:
        return False
    if cw > 0.5 * col_w or ch > 0.5 * col_h:
        return False  # spans much of the region — rule / ornament / frame
    if cw > 8 * ch or ch > 8 * cw:
        return False  # extreme aspect — a horizontal rule or vertical frame line
    return True


def line_features(gray: np.ndarray) -> dict:
    """Image-level features for one line crop (grayscale).

    Returns glyph_count (components passing ``is_glyph``), n_components (all
    foreground components), height (px), and ink_density (fraction of foreground
    pixels). ink_density is a page-relative quantity — compare it to the page
    median in ``classify_page`` rather than to an absolute threshold.
    """
    h, w = gray.shape[:2]
    fg = (_binarize(gray) > 0).astype(np.uint8)
    n_labels, _, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    glyph_count = 0
    for i in range(1, n_labels):  # label 0 is background
        cx, cy, cw, ch, area = stats[i]
        if is_glyph(cw, ch, area, w, h):
            glyph_count += 1
    ink_density = float(fg.sum()) / float(h * w) if h and w else 0.0
    return {
        "glyph_count": glyph_count,
        "n_components": n_labels - 1,
        "height": int(h),
        "ink_density": ink_density,
    }


def page_median_ink(features: dict[str, dict]) -> float:
    """Median ink_density across a page's lines (dominated by real text)."""
    inks = [f["ink_density"] for f in features.values()]
    return float(np.median(inks)) if inks else 0.0


def classify_page(
    features: dict[str, dict], *, ink_factor: float = DEFAULT_INK_FACTOR
) -> dict[str, bool]:
    """Map line_id -> is_non_character for one page.

    A line is non-character when::

        glyph_count == 0                          # rules + blank/speck fragments
        OR ink_density > ink_factor * page_median # dense ornament bands

    Using the page median (not an absolute darkness) keeps the rule scan- and
    page-invariant.
    """
    median = page_median_ink(features)
    out: dict[str, bool] = {}
    for line_id, f in features.items():
        high_ink = median > 0 and f["ink_density"] > ink_factor * median
        out[line_id] = f["glyph_count"] == 0 or high_ink
    return out


def ocr_is_repetitive(text: str, *, min_repeats: int = 4, max_unit: int = 3) -> bool:
    """Optional escape-hatch fallback: True if ``text`` is a short unit repeated.

    Catches degenerate OCR like ``ողողողող`` that the image signals miss. This is
    a documented fallback, NOT the primary signal — keep it off unless the image
    rule alone cannot reach 100% on the labeled lines.
    """
    s = "".join(text.split())
    if len(s) < min_repeats * 1:
        return False
    for unit in range(1, max_unit + 1):
        if len(s) < unit * min_repeats:
            continue
        seg = s[:unit]
        if seg * (len(s) // unit) == s[: unit * (len(s) // unit)] and len(s) // unit >= min_repeats:
            return True
    return False
