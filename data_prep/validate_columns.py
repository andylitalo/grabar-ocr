"""
validate_columns.py
Gate harness for the automated deskew + two-column slicer.

Validates against the existing gold pages WITHOUT requiring pixel-aligned gold
boxes (none were recorded, and gold column crops were per-column-deskewed). It
relies on self-contained, geometry-grounded checks plus optional comparisons:

  deskew gate (--check deskew):
    - residual skew after correction (re-estimated) is ~0
    - projection sharpness never decreases
    - ink mass preserved through the rotation

  column gate (default):
    - no-clip edge test: few foreground pixels lie on any box border, so no
      letter is bisected and no marginalia bleeds across an edge
    - gutter separation: the gutter density is far below in-column density
    - line-count vs gold data/lines (informational; confounded by the gold
      render's different DPI, so reported, not gated)
    - IoU vs human-verified boxes when present (data/columns/boxes, source=human)

Writes nothing into the frozen dataset; any crops go to a scratch dir.

Usage:
    python -m data_prep.validate_columns --check deskew --pages 51,200,...
    python -m data_prep.validate_columns --pages 51,200,...
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from data_prep.column_detector import _binarize, detect_columns  # noqa: E402
from data_prep.deskew import _sharpness, deskew_page, estimate_skew_angle  # noqa: E402
from data_prep.line_cropper import crop_lines  # noqa: E402
from data_prep.pdf_slicer import pdf_to_images  # noqa: E402
from labeling_ui import pipeline, storage  # noqa: E402

logger = logging.getLogger("validate_columns")

GOLD_PAGES = [51, 200, 251, 300, 400, 451, 486, 487, 499, 543, 550, 559]

# Gate thresholds.
MAX_RESIDUAL_DEG = 0.15
MIN_SHARPNESS_RATIO = 1.0
MIN_INK_RATIO = 0.98
MAX_CLIPPED = 0  # glyphs a box edge may meaningfully truncate (no-clip)
CLIP_PX = 12  # poke beyond this many px = a glyph substantially cut
GRAZE_PX = 3  # poke beyond this = a minor stroke graze (informational only)
MAX_GUTTER_FRAC = 0.40  # gutter density / in-column density
MIN_IOU = 0.92


def _raw_render(n: int) -> np.ndarray:
    """Render page n straight from the PDF (no deskew), for before/after compare."""
    with tempfile.TemporaryDirectory() as td:
        rendered = pdf_to_images(storage.page_pdf_path(n), Path(td), dpi=pipeline.RENDER_DPI)
        return cv2.imread(str(rendered[0]), cv2.IMREAD_GRAYSCALE)


def check_deskew(pages: list[int]) -> bool:
    """Run the deskew gate; return True if every page passes."""
    print(f"\n{'page':10} {'angle':>7} {'residual':>9} {'sharp×':>7} {'ink':>6}  result")
    all_ok = True
    for n in pages:
        if not storage.page_pdf_path(n).exists():
            continue
        raw = _raw_render(n)
        deskewed, angle = deskew_page(raw)
        residual = estimate_skew_angle(deskewed)
        s_before = _sharpness(_binarize(raw))
        s_after = _sharpness(_binarize(deskewed))
        ratio = s_after / s_before if s_before else 1.0
        ink = float((255 - deskewed).sum()) / float((255 - raw).sum() or 1)
        ok = abs(residual) <= MAX_RESIDUAL_DEG and ratio >= MIN_SHARPNESS_RATIO and ink >= MIN_INK_RATIO
        all_ok &= ok
        print(
            f"page_{n:04d}  {angle:6.2f}  {residual:8.2f}  {ratio:6.2f}  {ink:5.3f}  "
            f"{'PASS' if ok else 'FAIL'}"
        )
    print(f"\nDeskew gate: {'PASS' if all_ok else 'FAIL'} "
          f"(residual ≤ {MAX_RESIDUAL_DEG}°, sharpness ≥ {MIN_SHARPNESS_RATIO}×, ink ≥ {MIN_INK_RATIO})")
    return all_ok


def _is_glyph(cw: int, ch: int, area: int, col_w: int, col_h: int) -> bool:
    """True if a component is plausibly a single glyph (not a rule/ornament/frame)."""
    if area < 20:
        return False
    if cw > 0.5 * col_w or ch > 0.5 * col_h:
        return False  # spans much of the column — rule / ornament / frame
    if cw > 8 * ch or ch > 8 * cw:
        return False  # extreme aspect — a horizontal rule or vertical frame line
    return True


def _clip_count(stats: np.ndarray, box: dict, *, min_outside: int, min_inside_frac: float = 0.5) -> int:
    """Number of glyph components clipped by a box edge by more than ``min_outside`` px.

    A clipped glyph belongs to this column (the majority of its bbox is inside the
    box) yet pokes past an edge. Marginalia (mostly outside) and non-glyph rules /
    ornaments are excluded. With a large ``min_outside`` this counts only
    meaningful truncation; with a small one it also counts minor stroke grazes.
    """
    x1, y1, x2, y2 = box["x1"], box["y1"], box["x2"], box["y2"]
    col_w, col_h = x2 - x1, y2 - y1
    count = 0
    for i in range(1, stats.shape[0]):
        cx, cy, cw, ch, area = stats[i]
        if not _is_glyph(cw, ch, area, col_w, col_h):
            continue
        bx2, by2 = cx + cw, cy + ch
        ix1, iy1 = max(cx, x1), max(cy, y1)
        ix2, iy2 = min(bx2, x2), min(by2, y2)
        if ix1 >= ix2 or iy1 >= iy2:
            continue  # no overlap with the box
        if (ix2 - ix1) * (iy2 - iy1) < min_inside_frac * (cw * ch):
            continue  # belongs to a margin / the other column, not here
        if (x1 - cx) > min_outside or (bx2 - x2) > min_outside or \
           (y1 - cy) > min_outside or (by2 - y2) > min_outside:
            count += 1
    return count


def _iou(a: dict, b: dict) -> float:
    ix1, iy1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    ix2, iy2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_a = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
    area_b = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _gold_line_counts(page_id: str) -> list[int]:
    out = []
    for i in (1, 2):
        d = storage.column_dir(page_id, i)
        n = len(list(d.glob("line_*.png"))) if d.is_dir() else 0
        rej = d / "rejected"
        n += len(list(rej.glob("line_*.png"))) if rej.is_dir() else 0
        out.append(n)
    return out


def check_columns(pages: list[int], scratch: Path | None) -> bool:
    """Run the column gate; return True if every confident page passes."""
    print(f"\n{'page':10} {'conf':5} {'clip>12':>7} {'graze':>6} {'gutter':>7} {'IoU':>6}  "
          f"{'det/gold lines':16} result")
    all_ok = True
    confident = 0
    for n in pages:
        page_id = storage.page_id_for(n)
        if not storage.page_pdf_path(n).exists():
            continue
        gray = cv2.imread(str(pipeline.render_page(n)), cv2.IMREAD_GRAYSCALE)
        boxes, diag = detect_columns(gray)
        if not diag.get("confident"):
            print(f"{page_id:10} DEFER  {'-':>7} {'-':>6} {'-':>7} {'-':>6}  "
                  f"{'-':16} ({diag.get('reason','')[:30]})")
            continue
        confident += 1
        binary = _binarize(gray)
        _, _, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), 8)

        clipped = sum(_clip_count(stats, b, min_outside=CLIP_PX) for b in boxes)
        grazes = sum(_clip_count(stats, b, min_outside=GRAZE_PX) for b in boxes)
        gutter_frac = diag["gutter_val"] / (diag["col_median"] or 1)

        # IoU against human-verified boxes only.
        rec = storage.load_boxes(page_id)
        iou = None
        if rec and rec.get("source") == "human" and len(rec.get("boxes", [])) == 2:
            iou = min(_iou(d, g) for d, g in zip(boxes, rec["boxes"]))

        # Line counts (informational).
        det_counts = "-"
        if scratch is not None:
            dc = []
            for i, b in enumerate(boxes, 1):
                crop = gray[b["y1"]:b["y2"], b["x1"]:b["x2"]]
                cp = scratch / f"{page_id}_c{i}.png"
                cv2.imwrite(str(cp), crop)
                dc.append(len(crop_lines(cp, scratch / f"{page_id}_l{i}", padding=4)))
            det_counts = f"{dc}/{_gold_line_counts(page_id)}"

        ok = clipped <= MAX_CLIPPED and gutter_frac <= MAX_GUTTER_FRAC
        if iou is not None:
            ok &= iou >= MIN_IOU
        all_ok &= ok
        iou_s = f"{iou:.3f}" if iou is not None else "n/a"
        print(f"{page_id:10} OK     {clipped:7d} {grazes:6d} {gutter_frac:7.3f} {iou_s:>6}  "
              f"{det_counts:16} {'PASS' if ok else 'FAIL'}")

    print(f"\nColumn gate: {'PASS' if all_ok else 'FAIL'} over {confident} confident page(s) "
          f"(glyphs cut >{CLIP_PX}px ≤ {MAX_CLIPPED}, gutter ≤ {MAX_GUTTER_FRAC}, IoU ≥ {MIN_IOU} when human boxes exist)")
    print(f"Note: 'graze' = glyphs grazed {GRAZE_PX}-{CLIP_PX}px at the gutter cut "
          "(inherent to any straight split; a human cut grazes the same) — informational.")
    print("Note: det/gold line counts are informational — gold crops came from a "
          "different-DPI render, so exact counts are not gated.")
    return all_ok


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser(description="Validate deskew + column slicing")
    parser.add_argument("--check", choices=["deskew", "columns", "all"], default="all")
    parser.add_argument("--pages", help="Comma-separated pages (default: the 12 gold pages)")
    parser.add_argument("--scratch", help="Dir for end-to-end line crops (enables line-count column)")
    args = parser.parse_args()

    pages = [int(x) for x in args.pages.split(",")] if args.pages else GOLD_PAGES
    scratch = Path(args.scratch) if args.scratch else None
    if scratch:
        scratch.mkdir(parents=True, exist_ok=True)

    ok = True
    if args.check in ("deskew", "all"):
        ok &= check_deskew(pages)
    if args.check in ("columns", "all"):
        ok &= check_columns(pages, scratch)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
