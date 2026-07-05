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

import re

import cv2
import numpy as np

# Default discriminator: a line is non-character when it has no glyph-like
# components at all (rules + specks) OR its ink is far above the page median
# (dense ornament bands). 1.6× sits well clear of the real-text max (≈1.15×) and
# below the junk min (≈2.2×); tune via the detect_nonchar_lines dry run.
DEFAULT_INK_FACTOR = 1.6

# Region types whose lines are EXEMPT from the high-ink ornament rule. A header's
# large display type is legitimately ink-dense — page_0560's heading measures
# ink ≈ 1.63× the page median, just over the 1.6× ornament cutoff, yet is real
# text (and now reads glyph 13 after the is_glyph display-capital fix). The
# ornament rule exists to catch decorative *bands* (heart motifs, dense dividers),
# which the slicer never emits as a `header` region. glyph_count == 0 still applies
# to every region, so a blank/rule line in a header is still caught. The line-id's
# leading segment carries the region type (``region_NN_<type>/line_NNN``); legacy
# ``column_N`` ids and bare ids have no type and are never exempt. Parsed with a
# local regex to keep this module dependency-free (no labeling_ui.storage import,
# per the module docstring) — the pattern mirrors storage.parse_region.
_HIGH_INK_EXEMPT_TYPES = frozenset({"header"})
_REGION_TYPE_RE = re.compile(r"^region_\d+_([a-z]+)/")


def region_type_of(line_id: str) -> str | None:
    """The region type embedded in a ``region_NN_<type>/line_NNN`` id, else None."""
    m = _REGION_TYPE_RE.match(line_id)
    return m.group(1) if m else None


def is_high_ink(line_id: str, ink_density: float, median: float,
                ink_factor: float = DEFAULT_INK_FACTOR) -> bool:
    """True if a line trips the ornament high-ink rule and is NOT an exempt region.

    Shared by ``classify_page`` and the report's reason string so the two can
    never disagree about whether a line is flagged for high ink.
    """
    if median <= 0 or ink_density <= ink_factor * median:
        return False
    return region_type_of(line_id) not in _HIGH_INK_EXEMPT_TYPES


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Otsu threshold to a foreground=255 mask (mirrors column_detector._binarize)."""
    _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


# A tall component is admitted as a display capital only if it is a *large* glyph
# with a letter-like bbox fill (extent = area / (cw*ch) — strokes leave most of the
# bbox empty; a solid bar fills it). _MIN_DISPLAY_CAP_PX separates true display
# type (page_0560 heading caps ≈ 48–54 px tall) from the small flecks / accent
# fragments / degraded marks that fill a SHORT crop's height (≤ ~20 px) and must
# stay rejected. Calibrated on the Phase A labeled crops at the 300-DPI render
# scale (data/_labeling_work renders); revisit alongside the header line-height
# multiplier in the Phase 6 gate calibration (validate_columns --check regions).
_GLYPH_EXTENT_MIN = 0.20
_GLYPH_EXTENT_MAX = 0.70
_MIN_DISPLAY_CAP_PX = 30


def is_glyph(cw: int, ch: int, area: int, col_w: int, col_h: int) -> bool:
    """True if a connected component is plausibly a single glyph (not a rule/ornament/frame).

    This is the single source of truth shared with data_prep.validate_columns,
    which aliases this function so the two never diverge.

    Display-capital fix (Phase 6): a tall component (ch > 0.5·col_h) is no longer
    blanket-rejected — in a tightly-cropped heading a large display capital
    naturally spans most of the crop height. It is accepted when it is a *large*,
    letter-like component: not spanning the region *width* (a rule / ornament band /
    frame), not an extreme aspect (a rule or frame line), at least
    ``_MIN_DISPLAY_CAP_PX`` tall (true display type, not a short-crop fleck), and
    with a stroke-like bbox fill. This rescues large headings (e.g. page_0560
    "ԵՕԹՆԵՐԵԱԿ", glyph 0 -> 13) without re-admitting ornament/divider bands. The
    rule is strictly a *superset* of the old one (it only ever accepts more), so no
    previously-counted real glyph is lost. (Thin/chopped real text — page_0080,
    page_0440 — is a line-slicing artifact, not separable here, and is left to the
    slicing phase.)
    """
    if area < 20:
        return False
    if cw > 8 * ch or ch > 8 * cw:
        return False  # extreme aspect — a horizontal rule or vertical frame line
    if cw > 0.5 * col_w:
        return False  # spans the region width — rule / ornament band / frame
    if ch > 0.5 * col_h:
        # Tall: a display capital (keep) or a short-crop fleck / vertical mark (drop).
        extent = area / float(cw * ch) if cw and ch else 1.0
        if ch < _MIN_DISPLAY_CAP_PX or not (_GLYPH_EXTENT_MIN <= extent <= _GLYPH_EXTENT_MAX):
            return False
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
                                                  # (header regions exempt — see
                                                  #  _HIGH_INK_EXEMPT_TYPES)

    Using the page median (not an absolute darkness) keeps the rule scan- and
    page-invariant. The high-ink half is suppressed for header regions, whose
    display type is legitimately dense (the line-id carries the region type).
    """
    median = page_median_ink(features)
    out: dict[str, bool] = {}
    for line_id, f in features.items():
        high_ink = is_high_ink(line_id, f["ink_density"], median, ink_factor)
        out[line_id] = f["glyph_count"] == 0 or high_ink
    return out


def max_glyph_run(text: str) -> int:
    """Length of the longest run of one identical character in ``text``.

    Whitespace breaks a run (a space is never part of a glyph run), so a repeated
    short word separated by spaces (``և և և``) does not count — only glyphs stacked
    directly against each other do.
    """
    best = run = 0
    prev: str | None = None
    for ch in text:
        if ch.isspace():
            prev, run = None, 0
            continue
        run = run + 1 if ch == prev else 1
        prev = ch
        if run > best:
            best = run
    return best


def distinct_glyphs(text: str) -> int:
    """Number of distinct non-whitespace characters in ``text``."""
    return len(set("".join(text.split())))


def is_glyph_run_divider(text: str, *, max_run: int = 3, max_distinct: int = 3) -> bool:
    """True if an OCR line is an ornamental divider / speck: a few glyphs repeated.

    Two conditions, both required:
      * a run of one glyph longer than ``max_run`` (the requested "never more than 3
        of the same glyph" signal), AND
      * at most ``max_distinct`` distinct glyphs on the whole line.

    The run alone is NOT safe on OCR *output*: Tesseract routinely stutters the
    leading glyph of a real line (``ՅՅՅՅունուար`` = January, ``ԴԴԴԴեկտեմբեր`` =
    December, ``ՕՕՕՕՕՕՕՕգԳոստոս`` = August), so a bare run>3 rule would drop real
    month headings. But a real line — even a badly stuttered one — always carries
    many distinct glyphs, while an ornamental divider / rule (``աաաաաաաաաաշշշշշշշշշշշ``,
    ``####…``, ``----``) is one-or-two glyphs repeated. Requiring low glyph diversity
    keeps only the genuine dividers. This is a *text* signal on the OCR beam, so it
    catches what the image filter misses (a rule whose strokes read as glyphs, so
    ``glyph_count`` > 0) and is backend-agnostic — it works for Tesseract, which
    computes no image features. Validated: 0 of 680 human-labeled real-text lines
    flagged; the ``ocr_is_repetitive`` single-unit-tiling test misses these two-run
    dividers.
    """
    return max_glyph_run(text) > max_run and distinct_glyphs(text) <= max_distinct


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
