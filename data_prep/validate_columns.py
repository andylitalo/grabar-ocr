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
import json
import logging
import re
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from data_prep.column_detector import _binarize, detect_columns, detect_regions  # noqa: E402
from data_prep.deskew import _sharpness, deskew_page, estimate_skew_angle  # noqa: E402
from data_prep.line_cropper import crop_lines  # noqa: E402
from data_prep.line_filter import is_glyph as _is_glyph  # noqa: E402  (shared glyph discriminator)
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

# --- region gate thresholds (Phase 6; calibrated against the human annotations) --
# Asymmetric tolerance for min ⊆ detected ⊆ max (gate #4), fit to the first
# human-annotation batch (see phase_6 doc):
#   MIN side — a detected edge may fall at most this far SHORT of the tight `min`
#   box (clipping real text is the real risk, so this is strict; the no-clip glyph
#   gate is a second guard). Observed worst underrun on clean pages: 12 px.
REGION_TOL_MIN_PX = 15
#   MAX side — a detected edge may run this far PAST the loose `max` box. The
#   detector includes a little more clean margin than the annotator's tight max;
#   that whitespace carries no frame ink (the 0-frame-edge gate is the real frame
#   guard), so this side is generous. Observed worst overrun on clean pages: 45 px.
REGION_TOL_MAX_PX = 55
# Deskew accuracy (gate #6): |auto angle − human reference-line angle| must be ≤
# this. Observed worst auto-vs-human residual: 0.32° (page_0080).
DESKEW_TOL_DEG = 0.35
# A box border is "on a rule" (frame/divider, gate #1/#2) when its longest
# contiguous foreground run covers at least this fraction of the border length.
# Short runs are ordinary text grazing the cut, not a rule.
EDGE_RULE_FRAC = 0.50


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
    """Placed+rejected line counts per region, in reading order (region_* / column_*)."""
    out = []
    for d in storage.region_dirs_in(storage.DATA_LINES / page_id):
        n = len(list(d.glob("line_*.png")))
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
        # Gold boxes/line crops live under the human artifact id (page_XXXX_human);
        # the detector is re-run live for the auto comparison.
        page_id = storage.page_artifact_id(n, storage.METHOD_HUMAN)
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


# --- region gate (Phase 6) ---------------------------------------------------


def _reading_order(boxes: list[dict]) -> list[dict]:
    """Canonical reading order from geometry: bands top-to-bottom, left→right within.

    Boxes that overlap vertically by more than half the shorter box's height share a
    band (two columns); a full-width header forms its own band. This makes the order
    independent of how regions were stored (the annotator's saved `order` is unused).
    """
    items = sorted(boxes, key=lambda b: b["y1"])
    bands: list[list[dict]] = []
    for b in items:
        bh = b["y2"] - b["y1"]
        for band in bands:
            top = min(x["y1"] for x in band)
            bot = max(x["y2"] for x in band)
            overlap = min(b["y2"], bot) - max(b["y1"], top)
            if overlap > 0.5 * min(bh, bot - top):
                band.append(b)
                break
        else:
            bands.append([b])
    bands.sort(key=lambda band: min(x["y1"] for x in band))
    out: list[dict] = []
    for band in bands:
        out.extend(sorted(band, key=lambda b: b["x1"]))
    return out


def _longest_edge_run(binary: np.ndarray, box: dict, side: str) -> float:
    """Longest contiguous foreground fraction along one box border (rule detector)."""
    x1, y1 = box["x1"], box["y1"]
    x2 = min(box["x2"], binary.shape[1] - 1)
    y2 = min(box["y2"], binary.shape[0] - 1)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    line = {
        "top": binary[y1, x1:x2], "bottom": binary[y2, x1:x2],
        "left": binary[y1:y2, x1], "right": binary[y1:y2, x2],
    }[side]
    mask = line > 0
    best = run = 0
    for v in mask:
        run = run + 1 if v else 0
        best = max(best, run)
    return best / max(1, len(mask))


def _contains(
    detected: dict, inner: dict, outer: dict,
    tol_min: int = REGION_TOL_MIN_PX, tol_max: int = REGION_TOL_MAX_PX,
) -> tuple[bool, bool]:
    """(detected ⊇ inner within tol_min, detected ⊆ outer within tol_max), per side."""
    covers_min = (
        detected["x1"] <= inner["x1"] + tol_min and detected["y1"] <= inner["y1"] + tol_min
        and detected["x2"] >= inner["x2"] - tol_min and detected["y2"] >= inner["y2"] - tol_min
    )
    within_max = (
        detected["x1"] >= outer["x1"] - tol_max and detected["y1"] >= outer["y1"] - tol_max
        and detected["x2"] <= outer["x2"] + tol_max and detected["y2"] <= outer["y2"] + tol_max
    )
    return covers_min, within_max


def _annotated_pages() -> list[int]:
    """Page numbers with a human region-schema annotation (data/columns/boxes)."""
    out: list[int] = []
    if not storage.DATA_COLUMN_BOXES.is_dir():
        return out
    for f in sorted(storage.DATA_COLUMN_BOXES.glob("page_*_human.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        m = re.match(r"page_(\d+)_human", f.stem)
        if m and isinstance(d, dict) and "regions" in d and d.get("source") == "human":
            out.append(int(m.group(1)))
    return sorted(out)


def check_regions(pages: list[int]) -> bool:
    """Region gate (#1–#6): structure + min/max containment vs human truth, no
    frame/divider ink on edges, no-clip preserved, deskew within tolerance."""
    print(f"\n{'page':12} {'det types':22} {'human types':22} "
          f"{'struct':6} {'min⊆det⊆max':12} {'clip':4} {'edge':5} {'Δdeskew':8} result")
    all_ok = True
    checked = 0
    deltas: list[float] = []
    for n in pages:
        page_id = storage.page_artifact_id(n, storage.METHOD_HUMAN)
        truth = storage.load_regions(page_id)
        if not truth or not storage.page_pdf_path(n).exists():
            continue
        checked += 1

        # Run the detector in the SAME frame the human annotated: the cached
        # auto-deskew render rotated by the human's manual residual.
        auto_angle = pipeline.deskew_angle(n)
        human_angle = float(truth.get("deskew_angle", auto_angle))
        manual = human_angle - auto_angle
        gray = cv2.imread(str(pipeline.preview_render(n, manual)), cv2.IMREAD_GRAYSCALE)
        regions, diag = detect_regions(gray)

        human_boxes = [{**r["max"], "type": r["type"], "min": r["min"], "max": r["max"]}
                       for r in truth["regions"]]
        h_order = _reading_order(human_boxes)
        d_order = _reading_order([dict(r) for r in regions]) if regions else []
        h_types = [b["type"] for b in h_order]
        d_types = [b["type"] for b in d_order]
        struct = d_types == h_types

        # Gate #4: min ⊆ detected ⊆ max (only meaningful when structure matches).
        contain_ok = struct
        if struct:
            for det, hum in zip(d_order, h_order):
                cmin, cmax = _contains(det, hum["min"], hum["max"])
                contain_ok &= cmin and cmax

        # Gate #5: no-clip — glyphs a detected edge cuts by > CLIP_PX.
        binary = _binarize(gray)
        _, _, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), 8)
        clipped = sum(_clip_count(stats, r, min_outside=CLIP_PX) for r in regions)

        # Gate #1/#2: no frame ink on any edge; no divider ink on a two-column
        # band's inner edge (a long contiguous run on a border = a rule).
        edge_rule = 0
        for r in d_order:
            for side in ("top", "bottom", "left", "right"):
                if _longest_edge_run(binary, r, side) >= EDGE_RULE_FRAC:
                    edge_rule += 1

        # Gate #6: deskew accuracy vs the human reference-line angle.
        delta = abs(manual)
        deltas.append(delta)

        ok = struct and contain_ok and clipped <= MAX_CLIPPED and edge_rule == 0 \
            and delta <= DESKEW_TOL_DEG
        all_ok &= ok
        print(f"{page_id:12} {','.join(d_types)[:22]:22} {','.join(h_types)[:22]:22} "
              f"{'OK' if struct else 'DIFF':6} {'OK' if contain_ok else 'FAIL':12} "
              f"{clipped:4d} {edge_rule:5d} {delta:7.2f}° {'PASS' if ok else 'FAIL'}")

    worst = max(deltas) if deltas else 0.0
    print(f"\nRegion gate: {'PASS' if all_ok else 'FAIL'} over {checked} annotated page(s) "
          f"(struct match, det⊇min −{REGION_TOL_MIN_PX}px & det⊆max +{REGION_TOL_MAX_PX}px, "
          f"glyphs cut >{CLIP_PX}px ≤ {MAX_CLIPPED}, 0 frame/divider edges, "
          f"|Δdeskew| ≤ {DESKEW_TOL_DEG}°)")
    print(f"Deskew: worst auto-vs-human delta = {worst:.2f}° (gate ≤ {DESKEW_TOL_DEG}°).")
    return all_ok


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser(description="Validate deskew + column / region slicing")
    parser.add_argument("--check", choices=["deskew", "columns", "regions", "all"], default="all")
    parser.add_argument("--pages", help="Comma-separated pages (default: gold pages, or "
                        "the annotated pages for --check regions)")
    parser.add_argument("--scratch", help="Dir for end-to-end line crops (enables line-count column)")
    args = parser.parse_args()

    scratch = Path(args.scratch) if args.scratch else None
    if scratch:
        scratch.mkdir(parents=True, exist_ok=True)

    ok = True
    if args.check in ("deskew", "all"):
        ok &= check_deskew([int(x) for x in args.pages.split(",")] if args.pages else GOLD_PAGES)
    if args.check in ("columns", "all"):
        ok &= check_columns([int(x) for x in args.pages.split(",")] if args.pages else GOLD_PAGES, scratch)
    if args.check in ("regions", "all"):
        region_pages = [int(x) for x in args.pages.split(",")] if args.pages else _annotated_pages()
        ok &= check_regions(region_pages)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
