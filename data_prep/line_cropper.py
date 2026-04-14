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


def horizontal_projection(gray: np.ndarray) -> np.ndarray:
    """Return sum of dark (inverted) pixel values per row."""
    inverted = 255 - gray
    return inverted.sum(axis=1).astype(np.float32)


def find_line_boundaries(
    projection: np.ndarray,
    min_gap_height: int = 5,
    threshold_fraction: float = 0.02,
) -> list[tuple[int, int]]:
    """Identify (top, bottom) row pairs for each text line.

    A row is considered "text" if its projection value exceeds
    `threshold_fraction` of the maximum projection value.
    """
    max_val = projection.max()
    threshold = threshold_fraction * max_val
    is_text_row = projection > threshold

    boundaries: list[tuple[int, int]] = []
    in_line = False
    start = 0

    for row_idx, is_text in enumerate(is_text_row):
        if is_text and not in_line:
            start = row_idx
            in_line = True
        elif not is_text and in_line:
            height = row_idx - start
            if height >= min_gap_height:
                boundaries.append((start, row_idx))
            in_line = False

    # Close final line if it runs to the bottom of the image
    if in_line:
        boundaries.append((start, len(is_text_row)))

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

    projection = horizontal_projection(image)
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
