"""Dump kraken line-segmentation geometry for the review UI.

Runs kraken neural baseline segmentation (``blla.segment``) on each source page
PDF and persists, per page, the artifacts the standalone review UI
(``dev/kraken_review/``) reads:

  dev/kraken_review/data/page_<N>/render.png        300-DPI page image (RGB)
  dev/kraken_review/data/page_<N>/segmentation.json line polygons/baselines/bboxes

Unlike ``dev/test_kraken_doc_layout.py`` (which only writes per-line JPEGs and a
diagnostic overlay), this script persists the *geometry* so the UI can draw
clickable polygons and hit-test clicks. It imports kraken, so it must run under
the dev virtualenv that has kraken installed:

    dev/venv-grabar/bin/python dev/kraken_segment.py

The UI itself never imports kraken — it only reads the JSON + PNG emitted here.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pypdfium2 as pdfium

from kraken import binarization, blla
from kraken.lib import vgsl

MODEL_PATH = "/Users/andylitalo/Library/Application Support/htrmopo/97665cf3-f83d-5594-8855-f28d3af9df7a/blla.mlmodel"
# Default set (the original 9 test pages) used when no --range/--pages is given.
DEFAULT_PAGES = [448, 530, 546, 551, 552, 555, 557, 564, 641]

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = REPO_ROOT / "data" / "pages"
OUT_ROOT = Path(__file__).resolve().parent / "kraken_review" / "data"
RENDER_DPI = 300


def _points(seq) -> list[list[float]]:
    """Normalize a kraken point sequence into a JSON-friendly list of [x, y]."""
    if not seq:
        return []
    return [[float(x), float(y)] for x, y in seq]


def _bbox(boundary: list[list[float]], bounds) -> list[float] | None:
    """Axis-aligned bounding box from a polygon, falling back to legacy bounds."""
    if boundary:
        xs = [p[0] for p in boundary]
        ys = [p[1] for p in boundary]
        return [min(xs), min(ys), max(xs), max(ys)]
    if bounds is not None:
        return [float(v) for v in bounds]
    return None


def segment_page(page_num: int, seg_model, force: bool = False) -> None:
    pdf_path = PAGES_DIR / f"{page_num}.pdf"
    if not pdf_path.exists():
        print(f"  ⚠️  {pdf_path} not found; skipping")
        return

    out_dir = OUT_ROOT / f"page_{page_num}"
    if not force and (out_dir / "segmentation.json").exists():
        print(f"  ⏭️  page_{page_num}: already generated; skipping (use --force to redo)")
        return
    out_dir.mkdir(parents=True, exist_ok=True)

    # Render page 1 of the single-page PDF at 300 DPI (matches the dev script).
    pdf = pdfium.PdfDocument(str(pdf_path))
    bitmap = pdf[0].render(scale=RENDER_DPI / 72)
    pil_img = bitmap.to_pil().convert("RGB")
    width, height = pil_img.size

    render_path = out_dir / "render.png"
    pil_img.save(render_path, "PNG")

    # Binarize + neural baseline segmentation.
    bw_img = binarization.nlbin(pil_img)
    layout = blla.segment(bw_img, model=seg_model)

    lines_out = []
    for idx, line in enumerate(layout.lines, start=1):
        boundary = _points(getattr(line, "boundary", None))
        baseline = _points(getattr(line, "baseline", None))
        bbox = _bbox(boundary, getattr(line, "bounds", None))
        lines_out.append(
            {
                "index": idx,
                "id": f"line_{idx:03d}",
                "kraken_id": getattr(line, "id", None),
                "boundary": boundary,
                "baseline": baseline or None,
                "bbox": bbox,
            }
        )

    seg = {
        "page": page_num,
        "source_pdf": str(pdf_path),
        "model": Path(MODEL_PATH).name,
        "width": width,
        "height": height,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lines": lines_out,
    }
    (out_dir / "segmentation.json").write_text(json.dumps(seg, indent=2), encoding="utf-8")
    print(f"  ✓ page_{page_num}: {len(lines_out)} lines -> {out_dir}")


def _parse_pages(args) -> list[int]:
    if args.range:
        try:
            start, end = (int(x) for x in args.range.split("-"))
        except ValueError:
            raise SystemExit(f"--range must look like START-END, got {args.range!r}")
        if end < start:
            raise SystemExit(f"--range end {end} is before start {start}")
        return list(range(start, end + 1))
    if args.pages:
        return [int(p) for p in args.pages.split(",") if p.strip()]
    return list(DEFAULT_PAGES)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump kraken line-segmentation geometry for the review UI."
    )
    parser.add_argument("--range", help="inclusive page range, e.g. 448-648")
    parser.add_argument("--pages", help="explicit comma-separated page numbers, e.g. 448,530,546")
    parser.add_argument(
        "--force", action="store_true",
        help="re-generate pages that already have a segmentation.json",
    )
    args = parser.parse_args()

    pages = _parse_pages(args)
    print(f"Loading kraken segmentation model... ({len(pages)} page(s) requested)")
    seg_model = vgsl.TorchVGSLModel.load_model(MODEL_PATH)
    for i, page in enumerate(pages, start=1):
        print(f"[{i}/{len(pages)}] Segmenting page {page}...")
        segment_page(page, seg_model, force=args.force)
    print(f"\nDone. Segmentation geometry written under {OUT_ROOT}")


if __name__ == "__main__":
    main()
