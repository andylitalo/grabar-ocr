"""
deskew.py
Full-page skew correction for scanned Grabar pages.

Strategy: projection-profile variance maximization. A page whose text rows are
aligned to image scanlines produces a horizontal projection with sharp
peaks (text) and deep valleys (leading); rotating away from that alignment
smears the profile and lowers its variance. We search rotation angles and keep
the one that maximizes profile sharpness. This is more robust on Bolorgir than
Hough-line estimation alone (no long rules, dense diacritics), so Hough is used
only as an optional hint to focus the search.

Operates on the full page BEFORE column detection. Reuses
``line_cropper.horizontal_projection`` semantics (dark-pixel row sums) but scores
on an Otsu-binarized, downscaled copy for speed and contrast stability.

Usage:
    python -m data_prep.deskew --image data/_labeling_work/page_0051/page.png
"""

from __future__ import annotations

import argparse
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Long side (px) the angle search downscales to. The found angle is then applied
# to the full-resolution page.
_SEARCH_LONG_SIDE = 1000

# Pages with less foreground ink than this fraction are treated as blank: skew is
# undefined and noise would drive the search to the clamp, so we leave them as-is.
_MIN_FOREGROUND_FRAC = 0.005

# Score only this central window of the rotated image so the moving black borders
# introduced by rotation cannot bias the sharpness toward extreme angles.
_SCORE_CROP_H, _SCORE_CROP_W = 0.70, 0.80


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Otsu threshold to a binary image where text pixels are 255."""
    _, binimg = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binimg


def _downscale(gray: np.ndarray, long_side: int = _SEARCH_LONG_SIDE) -> np.ndarray:
    """Shrink so the longest side is ``long_side`` px (no-op if already smaller)."""
    h, w = gray.shape[:2]
    longest = max(h, w)
    if longest <= long_side:
        return gray
    scale = long_side / longest
    return cv2.resize(gray, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def _rotate(image: np.ndarray, angle: float, *, border: int, interp: int) -> np.ndarray:
    """Rotate about the image center by ``angle`` degrees (positive = CCW)."""
    h, w = image.shape[:2]
    rot = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    return cv2.warpAffine(
        image, rot, (w, h), flags=interp, borderMode=cv2.BORDER_CONSTANT, borderValue=border
    )


def _central_window(image: np.ndarray) -> np.ndarray:
    """Return the central crop used for scoring (keeps rotated borders out)."""
    h, w = image.shape[:2]
    ch, cw = int(h * _SCORE_CROP_H), int(w * _SCORE_CROP_W)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    return image[y0 : y0 + ch, x0 : x0 + cw]


def _sharpness(binary: np.ndarray) -> float:
    """Projection-profile sharpness of a binary image.

    Combines the variance of the row-sum profile with the energy of its first
    difference; both peak when text rows align to scanlines. Scored on a central
    window so the rotation's moving borders don't distort the profile.
    """
    profile = _central_window(binary).sum(axis=1).astype(np.float64)
    return float(profile.var() + np.square(np.diff(profile)).sum())


def _hough_hint(gray: np.ndarray, max_abs_angle: float) -> float | None:
    """Coarse skew estimate from near-horizontal Hough lines, or None."""
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=200)
    if lines is None:
        return None
    angles = []
    for rho, theta in lines[:, 0]:
        angle = np.degrees(theta) - 90.0
        if abs(angle) < max_abs_angle:
            angles.append(angle)
    if not angles:
        return None
    return float(np.median(angles))


def _best_angle_in(binary: np.ndarray, candidates: np.ndarray) -> tuple[float, float]:
    """Return (best_angle, best_score) over the candidate angles."""
    best_angle, best_score = 0.0, -np.inf
    for angle in candidates:
        rotated = _rotate(binary, float(angle), border=0, interp=cv2.INTER_NEAREST)
        score = _sharpness(rotated)
        if score > best_score:
            best_angle, best_score = float(angle), score
    return best_angle, best_score


def estimate_skew_angle(
    gray: np.ndarray,
    angle_range: float = 5.0,
    coarse_step: float = 0.5,
    fine_step: float = 0.1,
    hough_hint: bool = True,
) -> float:
    """Estimate the correction angle (degrees) that best deskews ``gray``.

    The returned angle is the rotation to APPLY (positive = CCW) so that text
    rows become horizontal; feed it to :func:`deskew_page`. After applying it,
    re-running this function on the result should yield ~0.
    """
    if gray.ndim != 2:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    # Near-blank pages have no defined skew; noise would drive the search to the
    # clamp. Leave them unrotated.
    coarse_bin = _binarize(_downscale(gray))
    if coarse_bin.mean() / 255.0 < _MIN_FOREGROUND_FRAC:
        logger.debug("Page near-blank (fg < %.1f%%); skipping deskew", _MIN_FOREGROUND_FRAC * 100)
        return 0.0

    # Coarse pass on a downscaled copy (fast), full range.
    coarse = np.arange(-angle_range, angle_range + coarse_step / 2, coarse_step)
    best_coarse, _ = _best_angle_in(coarse_bin, coarse)

    centers = [best_coarse]
    if hough_hint:
        hint = _hough_hint(_downscale(gray), angle_range)
        if hint is not None:
            centers.append(hint)

    # Fine pass at FULL resolution: a 0.1 deg error shifts page-edge rows by
    # several pixels, smearing the full-res projection the line cropper relies on,
    # so the downscaled coarse optimum is not precise enough on its own.
    fine_bin = _binarize(gray)
    best_angle, best_score = best_coarse, -np.inf
    span = max(coarse_step, fine_step * 5)
    for center in centers:
        lo = max(-angle_range, center - span)
        hi = min(angle_range, center + span)
        fine = np.arange(lo, hi + fine_step / 2, fine_step)
        angle, score = _best_angle_in(fine_bin, fine)
        if score > best_score:
            best_angle, best_score = angle, score

    logger.debug("Estimated skew correction: %.2f deg", best_angle)
    return best_angle


def deskew_page(gray: np.ndarray, max_abs_angle: float = 5.0) -> tuple[np.ndarray, float]:
    """Deskew a full page. Returns (deskewed_image, applied_angle_degrees).

    Estimates the correction angle (clamped to ``max_abs_angle``) and applies it
    to the full-resolution image with cubic interpolation and replicated borders
    so no ink is lost at the edges. Angles below 0.05 deg are treated as zero.
    """
    if gray.ndim != 2:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    angle = estimate_skew_angle(gray, angle_range=max_abs_angle)
    angle = float(np.clip(angle, -max_abs_angle, max_abs_angle))
    if abs(angle) < 0.05:
        return gray, 0.0
    deskewed = _rotate(gray, angle, border=255, interp=cv2.INTER_CUBIC)
    # Replicate-style edge handling: warpAffine above used a white constant border,
    # which suits scanned pages (white paper) better than black.
    logger.info("Deskewed page by %.2f deg", angle)
    return deskewed, angle


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Estimate/apply full-page deskew")
    parser.add_argument("--image", required=True, help="Path to a page PNG")
    parser.add_argument("--output", help="If set, write the deskewed page here")
    parser.add_argument("--max-angle", type=float, default=5.0)
    args = parser.parse_args()

    gray = cv2.imread(args.image, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(f"Cannot read image: {args.image}")
    deskewed, angle = deskew_page(gray, max_abs_angle=args.max_angle)
    print(f"applied_angle_deg={angle:.3f}")
    if args.output:
        cv2.imwrite(args.output, deskewed)
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
