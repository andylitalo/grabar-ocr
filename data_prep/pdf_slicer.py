"""
pdf_slicer.py
Convert a raw scanned PDF into high-resolution PNG images (one per page).

Usage:
    python pdf_slicer.py --input gs://grabar-raw-pdfs/book.pdf \
                         --output /tmp/pages/ \
                         --dpi 300
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def pdf_to_images(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 300,
) -> list[Path]:
    """Convert every page of a PDF to a PNG at the given DPI.

    Args:
        pdf_path: Local path to the PDF file.
        output_dir: Directory where PNGs will be written.
        dpi: Rendering resolution. 300 is standard for OCR; 400+ for very fine script.

    Returns:
        List of paths to written image files, in page order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    written: list[Path] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        out_path = output_dir / f"page_{page_num + 1:04d}.png"
        pix.save(str(out_path))
        written.append(out_path)
        logger.info("Saved %s", out_path)

    doc.close()
    logger.info("Converted %d pages from %s", len(written), pdf_path)
    return written


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Slice a PDF into per-page PNG images")
    parser.add_argument("--input", required=True, help="Path to input PDF")
    parser.add_argument("--output", required=True, help="Output directory for PNGs")
    parser.add_argument("--dpi", type=int, default=300, help="Rendering DPI (default: 300)")
    args = parser.parse_args()

    pdf_to_images(
        pdf_path=Path(args.input),
        output_dir=Path(args.output),
        dpi=args.dpi,
    )


if __name__ == "__main__":
    main()
