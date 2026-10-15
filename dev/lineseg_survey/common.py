"""Shared plumbing for the Phase 8 line-segmentation survey.

Every candidate segmenter runs in its own virtualenv and writes the *same* geometry
shape the review UI already reads (``dev/kraken_review``'s ``segmentation.json``):

  data/lineseg_survey/<tool>/pages/page_<N>/segmentation.json
  data/lineseg_survey/<tool>/reviews/page_<N>.review.json      (written by the UI)

(Data lives under ``data/``, apart from this code.)

All tools segment the same 300-DPI render that ``dev/kraken_segment.py`` produced
(``dev/kraken_review/data/page_<N>/render.png``), so coordinates line up across
tools and the UI can serve one image per page.

Stdlib only, so every tool venv can import it (``sys.path`` insert of this dir).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SURVEY_DIR = Path(__file__).resolve().parent
REPO_ROOT = SURVEY_DIR.parent.parent
KRAKEN_DATA = REPO_ROOT / "dev" / "kraken_review" / "data"
SURVEY_DATA = REPO_ROOT / "data" / "lineseg_survey"

# Phase 8 §B2 step 3: stratified across the book's hard cases.
SAMPLE_PAGES = [
    453,  # title page, display faces
    457,  # two-column body + running header merged across the gutter
    488,  # merged-column debris
    519,  # two-column Vol I body
    530,  # illustration + Bible verse
    557,  # Vol II decorative header + taregir
    564,  # taregir mid-page
    575,  # clean Vol II laydown
    593,  # leap-pair taregir
    610,  # full-width titles
    641,  # Great Paschal table
    642,  # colophon
]

# Pages segmented but not scored: the Paschal table is cell-level and already
# hand-transcribed as a CSV (corpus/STRUCTURE.md).
TABLE_PAGES = {641}


def render_path(page: int) -> Path:
    return KRAKEN_DATA / f"page_{page}" / "render.png"


def tool_data_dir(tool: str, page: int) -> Path:
    return SURVEY_DATA / tool / "pages" / f"page_{page}"


def tool_reviews_dir(tool: str) -> Path:
    return SURVEY_DATA / tool / "reviews"


def bbox_of(points: list[list[float]]) -> list[float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def box_polygon(box: list[float]) -> list[list[float]]:
    x1, y1, x2, y2 = box
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def midline_baseline(box: list[float]) -> list[list[float]]:
    """Stand-in baseline for tools that emit none: the box's bottom-quarter line.

    Only the review UI and reading-order sorting consume it; it is never scored.
    """
    x1, y1, x2, y2 = box
    y = y1 + 0.75 * (y2 - y1)
    return [[x1, y], [x2, y]]


def order_by_blocks(lines: list[dict], blocks: list[dict]) -> list[dict]:
    """Reading order for tools whose line detector has none of its own.

    ``blocks`` are ``{"bbox": [...], "position": int}`` layout regions already in
    reading order. Each line joins the block it overlaps most (by area); blocks go in
    ``position`` order, lines within a block top-to-bottom then left-to-right. Lines
    that touch no block go last, top-to-bottom.
    """

    def overlap(a: list[float], b: list[float]) -> float:
        w = min(a[2], b[2]) - max(a[0], b[0])
        h = min(a[3], b[3]) - max(a[1], b[1])
        return w * h if w > 0 and h > 0 else 0.0

    def key(item: tuple[int, dict]) -> tuple:
        block_pos, line = item
        return (block_pos, line["bbox"][1], line["bbox"][0])

    orphan = 10**9
    tagged: list[tuple[int, dict]] = []
    for line in lines:
        best, best_pos = 0.0, orphan
        for b in blocks:
            ov = overlap(line["bbox"], b["bbox"])
            if ov > best:
                best, best_pos = ov, b["position"]
        tagged.append((best_pos, line))
    return [line for _, line in sorted(tagged, key=key)]


def write_segmentation(
    tool: str,
    page: int,
    lines: list[dict],
    *,
    width: int,
    height: int,
    model: str,
    extra: dict | None = None,
) -> Path:
    """Persist one page in the review UI's shape.

    ``lines`` must already be in reading order; each needs ``boundary`` (polygon),
    ``baseline`` and ``bbox``. Ids are assigned here as ``line_001..N``.
    """
    out_lines = []
    for i, line in enumerate(lines, start=1):
        rec = {
            "index": i,
            "id": f"line_{i:03d}",
            "boundary": line["boundary"],
            "baseline": line["baseline"],
            "bbox": line["bbox"],
        }
        for key in ("confidence", "text"):  # optional reviewer aids, never scored
            if line.get(key) is not None:
                rec[key] = line[key]
        out_lines.append(rec)
    record = {
        "page": page,
        "tool": tool,
        "model": model,
        "source_image": str(render_path(page).relative_to(REPO_ROOT)),
        "width": width,
        "height": height,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lines": out_lines,
        **(extra or {}),
    }
    out_dir = tool_data_dir(tool, page)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "segmentation.json"
    path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return path


def parse_pages(arg: str | None) -> list[int]:
    """``None`` → the sample; ``"453-643"`` / ``"457,530"`` otherwise."""
    if not arg:
        return list(SAMPLE_PAGES)
    pages: list[int] = []
    for part in arg.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return pages
