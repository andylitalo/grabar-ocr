"""
line_cropper.py
Slice a Classical Armenian column image into individual line crops.

Strategy: horizontal projection profile (sum of dark pixels per row).
A trough in the profile indicates inter-line whitespace; we split there.

Usage:
    python line_cropper.py --input /tmp/columns/page_0001_column.png \
                            --output /tmp/lines/page_0001/
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Slicing defaults. A run taller than MERGE_FACTOR x the median line height is
# treated as fused lines and split (over-segmentation guard).
MIN_LINE_HEIGHT = 5
THRESHOLD_FRACTION = 0.02
SMOOTH_WINDOW = 7
MERGE_FACTOR = 1.6
# A trough only counts as a real inter-line gap if it dips below this fraction of
# the smaller flanking peak. Merged Bolorgir lines trough at ~5-40% of the peak;
# a tall single line (big ascenders/diacritics) has no such deep interior dip.
TROUGH_DEPTH_FRACTION = 0.6
# A column inked for more than this fraction of the page height is a vertical frame
# rule / decorative border, not text — text columns are dark only where glyphs cross
# them (well under 50% even in a dense column). Such a rule puts an ink floor under
# EVERY row, so no inter-line gap ever drops below threshold and the whole column
# fuses into one "line". We blank these columns before projecting (see
# strip_vertical_rules). 0.7 cleanly separates rules (~100% inked) from text.
RULE_DARK_FRACTION = 0.7
_DARK_VALUE = 128


def strip_vertical_rules(
    gray: np.ndarray, dark_fraction: float = RULE_DARK_FRACTION
) -> np.ndarray:
    """Blank full-height vertical rules (frame / gutter borders) to background.

    Returns a copy with every column that is dark (< ``_DARK_VALUE``) for more than
    ``dark_fraction`` of the page height set to white, so the horizontal projection
    sees true inter-line whitespace instead of the rule's constant ink floor.
    Returns the input unchanged when no such column exists (the common case — clean
    columns are untouched, so this never alters line detection on rule-free pages).
    """
    h = gray.shape[0]
    if h == 0:
        return gray
    rule_cols = (gray < _DARK_VALUE).sum(axis=0) / h > dark_fraction
    if not rule_cols.any():
        return gray
    out = gray.copy()
    out[:, rule_cols] = 255
    return out


def horizontal_projection(gray: np.ndarray) -> np.ndarray:
    """Return sum of dark (inverted) pixel values per row."""
    inverted = 255 - gray
    return inverted.sum(axis=1).astype(np.float32)


def _smooth(profile: np.ndarray, window: int) -> np.ndarray:
    """Moving-average smooth (numpy-only) to suppress single-row spikes."""
    if window <= 1:
        return profile
    kernel = np.ones(window, dtype=np.float32) / window
    return np.convolve(profile, kernel, mode="same")


def _split_oversized_run(
    smoothed: np.ndarray,
    top: int,
    bottom: int,
    median_height: float,
    min_line_height: int,
    merge_factor: float = MERGE_FACTOR,
) -> list[tuple[int, int]]:
    """Split a run taller than ``merge_factor * median_height`` into single lines.

    A run that much taller than the typical line is two-or-more fused lines. We
    cut it at the deepest interior troughs of the smoothed profile, near the
    expected line-pitch positions. A cut is only accepted when the trough is
    clearly below its flanking peaks (so a single tall line is never split) and
    every resulting piece is at least ``min_line_height`` tall.
    """
    height = bottom - top
    if median_height <= 0 or height <= merge_factor * median_height:
        return [(top, bottom)]

    n_pieces = max(2, int(round(height / median_height)))

    cuts: list[int] = []
    for k in range(1, n_pieces):
        center = top + int(round(k * height / n_pieces))
        lo = max(top + min_line_height, center - min_line_height)
        hi = min(bottom - min_line_height, center + min_line_height)
        if lo >= hi:
            continue
        cut = lo + int(np.argmin(smoothed[lo:hi]))
        left_peak = float(smoothed[top:cut].max()) if cut > top else float(smoothed[cut])
        right_peak = float(smoothed[cut:bottom].max()) if cut < bottom else float(smoothed[cut])
        flank = min(left_peak, right_peak)
        # Reject shallow dips: not a real inter-line gap (guards single tall lines).
        if flank <= 0 or smoothed[cut] >= TROUGH_DEPTH_FRACTION * flank:
            continue
        cuts.append(cut)

    if not cuts:
        return [(top, bottom)]

    pieces: list[tuple[int, int]] = []
    prev = top
    for cut in sorted(set(cuts)):
        if cut - prev >= min_line_height:
            pieces.append((prev, cut))
            prev = cut
    # Attach the tail; merge it back if it is too short to stand alone.
    if bottom - prev >= min_line_height or not pieces:
        pieces.append((prev, bottom))
    else:
        last_top, _ = pieces[-1]
        pieces[-1] = (last_top, bottom)

    return pieces


def find_line_boundaries(
    projection: np.ndarray,
    min_line_height: int = MIN_LINE_HEIGHT,
    threshold_fraction: float = THRESHOLD_FRACTION,
    smooth_window: int = SMOOTH_WINDOW,
    merge_factor: float = MERGE_FACTOR,
) -> list[tuple[int, int]]:
    """Identify (top, bottom) row pairs for each text line.

    A row is "text" if its (raw) projection exceeds ``threshold_fraction`` of the
    maximum. Maximal runs of text-rows at least ``min_line_height`` tall are
    candidate lines; any run taller than ``merge_factor`` x the median line height
    is treated as two-or-more fused lines and split at its deepest interior
    troughs (the over-segmentation guard). Smoothing is applied only to the split
    valley search, never to the threshold detection (it would fuse adjacent lines).
    """
    projection = projection.astype(np.float32)
    if projection.size == 0:
        return []

    # Detect candidate runs on the RAW projection. Smoothing the profile before
    # thresholding fills shallow inter-line troughs and fuses adjacent lines, so
    # it is used only to locate split valleys inside oversized runs (below).
    max_val = float(projection.max())
    if max_val <= 0:
        return []
    threshold = threshold_fraction * max_val
    is_text_row = projection > threshold

    runs: list[tuple[int, int]] = []
    in_line = False
    start = 0
    for row_idx, is_text in enumerate(is_text_row):
        if is_text and not in_line:
            start = row_idx
            in_line = True
        elif not is_text and in_line:
            if row_idx - start >= min_line_height:
                runs.append((start, row_idx))
            in_line = False
    # Close final line if it runs to the bottom of the image.
    if in_line and len(is_text_row) - start >= min_line_height:
        runs.append((start, len(is_text_row)))

    if not runs:
        return []

    # Median run height = the typical single-line height; robust to the few
    # merged (oversized) runs we are about to split.
    median_height = float(np.median([b - t for t, b in runs]))

    # Smoothed copy used ONLY to locate the deepest interior valley when splitting
    # an oversized run (suppresses single-row spikes in the trough search).
    smoothed = _smooth(projection, smooth_window)

    boundaries: list[tuple[int, int]] = []
    for top, bottom in runs:
        boundaries.extend(
            _split_oversized_run(
                smoothed, top, bottom, median_height, min_line_height, merge_factor
            )
        )
    return boundaries


def crop_lines(
    column_image_path: Path,
    output_dir: Path,
    padding: int = 4,
) -> list[Path]:
    """Crop every text line from a column image and save as individual PNGs.

    Args:
        column_image_path: Path to the column PNG.
        output_dir: Directory to write line images into.
        padding: Extra pixels added above/below each line boundary.

    Returns:
        List of paths to saved line images.
    """
    image = cv2.imread(str(column_image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Cannot read: {column_image_path}")

    # Detect line boundaries on a copy with vertical frame rules removed (else a
    # full-height border fuses the whole column into one line); crop from the
    # original image so the saved line keeps its real pixels.
    projection = horizontal_projection(strip_vertical_rules(image))
    boundaries = find_line_boundaries(projection)

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    for line_idx, (top, bottom) in enumerate(boundaries):
        top_padded = max(0, top - padding)
        bottom_padded = min(image.shape[0], bottom + padding)
        crop = image[top_padded:bottom_padded, :]
        out_path = output_dir / f"line_{line_idx + 1:03d}.png"
        cv2.imwrite(str(out_path), crop)
        saved.append(out_path)

    logger.info("Extracted %d lines from %s", len(saved), column_image_path)
    return saved


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Crop text lines from a column image")
    parser.add_argument("--input", required=True, help="Path to column PNG")
    parser.add_argument("--output", required=True, help="Output directory for line crops")
    parser.add_argument("--padding", type=int, default=4, help="Row padding per line (default: 4)")
    args = parser.parse_args()

    crop_lines(
        column_image_path=Path(args.input),
        output_dir=Path(args.output),
        padding=args.padding,
    )


if __name__ == "__main__":
    main()
