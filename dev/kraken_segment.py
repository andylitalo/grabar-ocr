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
import statistics
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
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

# --- gutter-split post-processing tunables ---
# The two-column pages of this book are separated by a printed vertical rule (a "‖").
# We find that rule (the longest contiguous vertical ink run near page center), and split
# a line only when it straddles the rule with a real column boundary — a rule-ink column
# flanked by blank space on BOTH sides. That last test is what keeps genuine full-width
# titles ("ԵՕԹՆԵՐԵԱԿ ՀՈՈՎՄԱՅԵՅԻՈՑ N.") intact: their central word-gap is pure whitespace
# with no rule ink, and their letters touch on at least one side. Fractions are of page
# width unless noted.
_MIN_LINES = 6             # a page needs at least this many lines to bother detecting columns
_RULE_MIN_FRAC = 0.18      # the central vertical rule must be unbroken for >= this fraction of page height
_MIN_SIDE_FRAC = 0.15      # a spanning line (and each split piece) must reach this far past the rule
_SEARCH_FRAC = 0.05        # how far from the detected rule x to hunt for the actual rule within a line
_FLANK_FRAC = 0.03         # width of the flank window checked for blank space on each side of the rule
_GAP_COL_THRESHOLD = 0.03  # a column with < this ink fraction (over the line's height) counts as "blank"
_MIN_FLANK_BLANK = 12      # px of contiguous blank required on each side of the rule (rejects word-gaps)
_RULE_INK_MIN = 0.30       # min ink fraction (over the line's height) for a column to be the rule


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


def _detect_rule(dark: np.ndarray, width: int, height: int) -> tuple[int, float]:
    """Locate the printed central column rule; returns (rule_x, height_fraction).

    A rule is a thin vertical line unbroken for much of the page height, so we score
    each column by its LONGEST contiguous run of ink (dense Bolorgir text columns break
    into line-height segments and score far lower) and take the strongest column in the
    central third. The returned fraction lets the caller reject pages with no real rule.
    """
    run = np.zeros(width, dtype=np.int32)
    best = np.zeros(width, dtype=np.int32)
    for row in dark:                       # ~page-height iterations of width-wide vector ops
        run = np.where(row, run + 1, 0)
        best = np.maximum(best, run)
    lo, hi = int(0.30 * width), int(0.70 * width)
    band = best[lo:hi]
    rule_x = lo + int(band.argmax())
    return rule_x, float(band.max()) / height


def _has_blank_run(col_ink: np.ndarray, min_len: int) -> bool:
    """True if col_ink has a contiguous run of >= min_len near-blank columns."""
    best = cur = 0
    for v in col_ink:
        cur = cur + 1 if v < _GAP_COL_THRESHOLD else 0
        best = max(best, cur)
    return best >= min_len


def _find_rule_cut(dark: np.ndarray, bbox: list[float], rule_x: int, width: int) -> float | None:
    """x at which to split a line, or None if it isn't a real merged two-column line.

    Within a search window around the page rule, find the ink-heaviest column (the local
    rule — headers can offset it slightly from the body rule). Require it to actually be a
    rule (ink over the line's height) with blank space flanking it on BOTH sides. A
    full-width title's central word-gap has no rule ink; a title letter-stroke has ink
    touching it on one side — both correctly return None.
    """
    h_img, w_img = dark.shape
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    y1, y2 = max(0, y1), min(h_img, y2)
    if y2 - y1 < 3:
        return None
    search = int(_SEARCH_FRAC * width)
    a, b = max(x1, rule_x - search), min(x2, rule_x + search)
    if b - a < 7:
        return None
    col_ink = dark[y1:y2, a:b].mean(axis=0)
    ci = int(col_ink.argmax())
    if col_ink[ci] < _RULE_INK_MIN:            # no printed rule passes through this line
        return None
    cut = a + ci
    flank = int(_FLANK_FRAC * width)
    left = dark[y1:y2, max(0, cut - flank):max(1, cut - 3)].mean(axis=0)
    right = dark[y1:y2, cut + 4:min(w_img, cut + flank)].mean(axis=0)
    if not (_has_blank_run(left, _MIN_FLANK_BLANK) and _has_blank_run(right, _MIN_FLANK_BLANK)):
        return None
    return float(cut)


def _row_below_is_two_column(line: dict, lines: list[dict], gutter_x: float, median_h: float) -> bool:
    """True when the line immediately below `line` is split into a left- and a right-column box.

    This is the user's guard: only a merged two-column line has genuine two-column
    content directly beneath it. A full-width title/subtitle is followed by another
    full-width line (or nothing aligned), so this returns False and it stays intact.
    """
    x1, y1, x2, y2 = line["bbox"]
    lh = y2 - y1
    below = [
        m for m in lines
        if m is not line and m.get("bbox")
        and m["bbox"][1] >= y2 - 0.4 * lh                      # starts at/below this line's bottom
        and (m["bbox"][1] + m["bbox"][3]) / 2 > (y1 + y2) / 2  # and its center is below
    ]
    if not below:
        return False
    nearest_top = min(m["bbox"][1] for m in below)
    band = 0.7 * max(lh, median_h)
    row = [m for m in below if m["bbox"][1] <= nearest_top + band]
    left_side = any(m["bbox"][2] <= gutter_x for m in row)
    right_side = any(m["bbox"][0] >= gutter_x for m in row)
    return left_side and right_side


def _split_line(line: dict, cut_x: float) -> tuple[dict, dict]:
    """Split one line into a left and a right piece at cut_x (rectangular boundaries)."""
    x1, y1, x2, y2 = line["bbox"]
    baseline = line.get("baseline")
    y_base = statistics.fmean(p[1] for p in baseline) if baseline else (y1 + y2) / 2

    def piece(bx1: float, bx2: float) -> dict:
        return {
            "index": line["index"],   # placeholder; renumbered by _post_process
            "id": line["id"],         # placeholder; renumbered by _post_process
            "kraken_id": line.get("kraken_id"),
            "boundary": [[bx1, y1], [bx2, y1], [bx2, y2], [bx1, y2]],
            "baseline": [[bx1, y_base], [bx2, y_base]],
            "bbox": [float(bx1), float(y1), float(bx2), float(y2)],
            "split_from": line["id"],  # provenance: this piece came from an auto gutter-split
        }

    return piece(x1, cut_x), piece(cut_x, x2)


def _post_process(lines: list[dict], dark: np.ndarray, width: int, height: int) -> tuple[list[dict], list[dict]]:
    """Guarded gutter split: cut a merged two-column line into its left/right halves.

    A line is split only when ALL hold: (1) the page has a central column rule,
    (2) the line straddles that rule with column-width extent on both sides,
    (3) the line immediately below it is itself two-column, and (4) a real column
    boundary — rule ink flanked by blank on both sides — sits inside the line
    (see ``_find_rule_cut``). This deliberately leaves full-width titles/subtitles intact.

    Returns (possibly-rewritten lines, list of post-processing op records).
    """
    ops: list[dict] = []
    bboxed = [l for l in lines if l.get("bbox")]
    if len(bboxed) < _MIN_LINES:
        return lines, ops
    rule_x, rule_frac = _detect_rule(dark, width, height)
    if rule_frac < _RULE_MIN_FRAC:          # no clear central rule -> not a ruled two-column page
        return lines, ops

    min_side = _MIN_SIDE_FRAC * width       # a genuine merged line reaches well into both columns
    median_h = statistics.median([l["bbox"][3] - l["bbox"][1] for l in bboxed])

    result: list[dict] = []
    for line in lines:
        bb = line.get("bbox")
        straddles = bb is not None and bb[0] <= rule_x - min_side and bb[2] >= rule_x + min_side
        if straddles and _row_below_is_two_column(line, lines, rule_x, median_h):
            cut_x = _find_rule_cut(dark, bb, rule_x, width)
            # Both resulting pieces must be column-width, never a sliver.
            if (cut_x is not None
                    and cut_x - bb[0] >= min_side
                    and bb[2] - cut_x >= min_side):
                left, right = _split_line(line, cut_x)
                result.extend((left, right))
                ops.append({
                    "op": "gutter_split",
                    "source_index": line["index"],
                    "source_id": line["id"],
                    "at_x": round(cut_x, 1),
                    "left_box": left["bbox"],
                    "right_box": right["bbox"],
                })
                continue
        result.append(line)

    if ops:
        for i, line in enumerate(result, start=1):   # renumber into reading order
            line["index"] = i
            line["id"] = f"line_{i:03d}"
        ops.insert(0, {
            "op": "gutter_detected",
            "rule_x": rule_x,
            "rule_height_frac": round(rule_frac, 3),
            "n_splits": len(ops),
        })
    return result, ops


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

    # Guarded post-processing: split merged two-column lines at the gutter (see
    # _post_process). Uses the binarized image to require a real blank column gap,
    # so genuine full-width titles/subtitles are left intact.
    dark = np.asarray(bw_img.convert("L")) < 128
    lines_out, post_ops = _post_process(lines_out, dark, width, height)

    seg = {
        "page": page_num,
        "source_pdf": str(pdf_path),
        "model": Path(MODEL_PATH).name,
        "width": width,
        "height": height,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lines": lines_out,
        "post_processing": post_ops,
    }
    (out_dir / "segmentation.json").write_text(json.dumps(seg, indent=2), encoding="utf-8")
    split_note = f" ({len(post_ops) - 1} gutter-split)" if post_ops else ""
    print(f"  ✓ page_{page_num}: {len(lines_out)} lines{split_note} -> {out_dir}")


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
