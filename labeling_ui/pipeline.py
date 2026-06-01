"""
pipeline.py
Orchestration over the existing data_prep functions.

Turns a selected page PDF into a cached page render, then into per-column PNGs
(data/columns/) and per-line PNGs (data/lines/). Reuses, and does not
reimplement:
  - data_prep.pdf_slicer.pdf_to_images  (PDF -> page PNG @ DPI)
  - data_prep.layout_detector.deskew    (Hough deskew of a column crop)
  - data_prep.line_cropper.crop_lines    (column PNG -> line PNGs)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import cv2

from . import storage

# Make the sibling `data_prep/` package importable.
sys.path.insert(0, str(storage.REPO))
from data_prep.layout_detector import deskew  # noqa: E402
from data_prep.line_cropper import crop_lines  # noqa: E402
from data_prep.pdf_slicer import pdf_to_images  # noqa: E402

RENDER_DPI = 300


def render_page(n: int, dpi: int = RENDER_DPI) -> Path:
    """Render page-1 of data/pages/{n}.pdf to a cached grayscale PNG.

    Returns the path to the cached render. Re-renders if missing.
    """
    pdf_path = storage.page_pdf_path(n)
    if not pdf_path.exists():
        raise FileNotFoundError(f"No page PDF at {pdf_path}")

    page_id = storage.page_id_for(n)
    out_png = storage.WORK_DIR / page_id / "page.png"
    if out_png.exists():
        return out_png

    out_png.parent.mkdir(parents=True, exist_ok=True)
    # pdf_to_images names outputs page_0001.png (1-based within the file); a
    # one-page PDF yields exactly one image, which we move to our cache slot.
    rendered = pdf_to_images(pdf_path, out_png.parent, dpi=dpi)
    if not rendered:
        raise RuntimeError(f"No pages rendered from {pdf_path}")
    shutil.move(str(rendered[0]), str(out_png))
    return out_png


def page_dimensions(render_path: Path) -> tuple[int, int]:
    """(width, height) in full-resolution pixels of a rendered page."""
    image = cv2.imread(str(render_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Cannot read render: {render_path}")
    h, w = image.shape[:2]
    return w, h


def default_columns(width: int, height: int) -> list[dict]:
    """Two suggested column boxes the user then nudges (left/right halves)."""
    mx = round(0.02 * width)
    my = round(0.01 * height)
    gutter = round(0.02 * width)
    mid = width // 2
    return [
        {"x1": mx, "y1": my, "x2": mid - gutter // 2, "y2": height - my},
        {"x1": mid + gutter // 2, "y1": my, "x2": width - mx, "y2": height - my},
    ]


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def crop_columns_and_lines(
    n: int,
    columns: list[dict],
    do_deskew: bool = True,
    padding: int = 4,
) -> list[dict]:
    """Crop each column from the page render and segment it into line PNGs.

    Each rectangle is in full-resolution page pixels. Column i (1-based) is
    written to data/columns/{page_id}_column_{i}.png, then crop_lines() fills
    data/lines/{page_id}/column_{i}/. Returns per-column line counts.
    """
    page_id = storage.page_id_for(n)
    render_path = render_page(n)
    page = cv2.imread(str(render_path), cv2.IMREAD_GRAYSCALE)
    if page is None:
        raise FileNotFoundError(f"Cannot read render: {render_path}")
    h, w = page.shape[:2]

    storage.DATA_COLUMNS.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for i, box in enumerate(columns, start=1):
        x1 = _clamp(int(box["x1"]), 0, w)
        y1 = _clamp(int(box["y1"]), 0, h)
        x2 = _clamp(int(box["x2"]), 0, w)
        y2 = _clamp(int(box["y2"]), 0, h)
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))

        crop = page[y1:y2, x1:x2]
        if do_deskew:
            crop = deskew(crop)

        column_png = storage.DATA_COLUMNS / f"{page_id}_column_{i}.png"
        cv2.imwrite(str(column_png), crop)

        col_dir = storage.column_dir(page_id, i)
        # Re-crop: clear stale line PNGs (and rejected/) before re-segmenting.
        if col_dir.exists():
            shutil.rmtree(col_dir)
        saved = crop_lines(column_png, col_dir, padding=padding)
        results.append({"column": i, "line_count": len(saved)})

    return results
