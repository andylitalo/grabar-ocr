"""
layout_detector.py
Use YOLOv8 to detect the Classical Armenian column on a page image and return
its bounding box. Also handles deskewing before detection.

Usage:
    python layout_detector.py --image /tmp/pages/page_0001.png \
                               --model weights/layout_yolov8.pt \
                               --output /tmp/columns/
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Class index in the YOLOv8 model that corresponds to "armenian_column".
# Update this once the model is trained.
ARMENIAN_COLUMN_CLASS_ID = 2


def deskew(image: np.ndarray) -> np.ndarray:
    """Rotate the image to correct for skew using Hough line detection."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=200)
    if lines is None:
        return image

    angles = []
    for rho, theta in lines[:, 0]:
        angle = np.degrees(theta) - 90
        if abs(angle) < 10:  # Only correct small skew angles
            angles.append(angle)

    if not angles:
        return image

    median_angle = float(np.median(angles))
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    rot_mat = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    deskewed = cv2.warpAffine(image, rot_mat, (w, h), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE)
    logger.debug("Deskewed by %.2f degrees", median_angle)
    return deskewed


def detect_armenian_column(
    image_path: Path,
    model_path: Path,
    confidence_threshold: float = 0.5,
) -> tuple[int, int, int, int] | None:
    """Run YOLOv8 layout detection and return the bounding box of the Armenian column.

    Returns:
        (x1, y1, x2, y2) pixel coordinates, or None if no column detected.
    """
    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise ImportError("ultralytics is required: pip install ultralytics") from e

    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    image = deskew(image)
    model = YOLO(str(model_path))
    results = model(image, conf=confidence_threshold, verbose=False)

    for result in results:
        for box in result.boxes:
            if int(box.cls) == ARMENIAN_COLUMN_CLASS_ID:
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                logger.info("Detected Armenian column at (%d,%d)-(%d,%d)", x1, y1, x2, y2)
                return x1, y1, x2, y2

    logger.warning("No Armenian column detected in %s", image_path)
    return None


def crop_and_save(
    image_path: Path,
    bbox: tuple[int, int, int, int],
    output_path: Path,
) -> Path:
    """Crop the detected column region and save it."""
    image = cv2.imread(str(image_path))
    x1, y1, x2, y2 = bbox
    cropped = image[y1:y2, x1:x2]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), cropped)
    logger.info("Saved column crop to %s", output_path)
    return output_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Detect Armenian column in a page image")
    parser.add_argument("--image", required=True)
    parser.add_argument("--model", required=True, help="Path to YOLOv8 .pt weights")
    parser.add_argument("--output", required=True, help="Output directory for column crops")
    args = parser.parse_args()

    image_path = Path(args.image)
    output_dir = Path(args.output)
    bbox = detect_armenian_column(image_path, Path(args.model))
    if bbox:
        stem = image_path.stem
        crop_and_save(image_path, bbox, output_dir / f"{stem}_column.png")
    else:
        logger.error("Skipping %s — no column detected", image_path)


if __name__ == "__main__":
    main()
