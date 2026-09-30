"""Filesystem layer for the kraken line-segmentation review UI.

Everything is on-disk state (no DB), mirroring ``labeling_ui/storage.py``:

  dev/kraken_review/data/page_<N>/render.png         (written by dev/kraken_segment.py)
  dev/kraken_review/data/page_<N>/segmentation.json  (written by dev/kraken_segment.py)
  dev/kraken_review/reviews/page_<N>.review.json     (written here, by the UI)

Page numbers are the raw source-PDF numbers (e.g. 448), matching the dev
kraken experiment — not the zero-padded ``page_0448`` ids used in production.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REVIEWS_DIR = BASE_DIR / "reviews"
# Renders are shared: every survey tool segments kraken's 300-DPI render.
RENDER_DIR = DATA_DIR
SURVEY_DIR = BASE_DIR.parent / "lineseg_survey"
TOOL: str | None = None  # None = the original kraken review (paths above)


def configure(tool: str | None) -> None:
    """Point the UI at one Phase 8 survey tool's geometry and reviews.

    ``dev/lineseg_survey/<tool>/{data,reviews}``; renders still come from
    ``dev/kraken_review/data``. ``None`` keeps the original kraken review paths.
    """
    global DATA_DIR, REVIEWS_DIR, TOOL
    TOOL = tool
    if tool:
        DATA_DIR = SURVEY_DIR / tool / "data"
        REVIEWS_DIR = SURVEY_DIR / tool / "reviews"

# category number -> human label; the single source of truth for the taxonomy.
CATEGORY_LABELS = {
    1: "over-segmentation",
    2: "under-segmentation",
    3: "non-text",
    4: "clips ink",             # polygon cuts off ascenders/descenders/drop-cap ink
    5: "out of reading order",  # line sits in the wrong place in the order
}

_PAGE_DIR_RE = re.compile(r"^page_(\d+)$")

# Page review status. "reviewed" locks the page in the UI and is what score.py counts.
STATUSES = ("in_progress", "reviewed")


def data_dir(page: int) -> Path:
    return DATA_DIR / f"page_{page}"


def render_path(page: int) -> Path:
    return RENDER_DIR / f"page_{page}" / "render.png"


def segmentation_path(page: int) -> Path:
    return data_dir(page) / "segmentation.json"


def review_path(page: int) -> Path:
    return REVIEWS_DIR / f"page_{page}.review.json"


def list_pages() -> list[int]:
    """Page numbers that have a segmentation.json to review, sorted ascending."""
    if not DATA_DIR.exists():
        return []
    pages: list[int] = []
    for child in DATA_DIR.iterdir():
        m = _PAGE_DIR_RE.match(child.name)
        if m and (child / "segmentation.json").exists():
            pages.append(int(m.group(1)))
    return sorted(pages)


def reviewed_pages() -> list[int]:
    """Pages whose saved review has status "reviewed"."""
    return [p for p in list_pages()
            if review_path(p).exists() and load_review(p)["status"] == "reviewed"]


def load_segmentation(page: int) -> dict:
    path = segmentation_path(page)
    if not path.exists():
        raise FileNotFoundError(f"No segmentation for page {page}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# Correction-op lists added alongside flags/missed_lines. Kept as empty defaults
# so older reviews (which lack these keys) still load and round-trip cleanly.
_CORRECTION_KEYS = ("initials", "merges", "splits", "section_titles")


def load_review(page: int) -> dict:
    """Existing review for a page, or an empty skeleton if none saved yet."""
    path = review_path(page)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("flags", {})
        data.setdefault("missed_lines", [])
        data.setdefault("status", "in_progress")
        for key in _CORRECTION_KEYS:
            data.setdefault(key, [])
        return data
    skeleton = {"page": page, "status": "in_progress", "flags": {}, "missed_lines": []}
    skeleton.update({key: [] for key in _CORRECTION_KEYS})
    return skeleton


def _validate_box(box_raw, ctx: str) -> list[float]:
    box = [float(v) for v in box_raw]
    if len(box) != 4:
        raise ValueError(f"{ctx} box must have 4 coords [x1,y1,x2,y2], got {box_raw!r}")
    return box


def _validate_line_ref(line_id, valid_ids: set[str], ctx: str, *, allow_none: bool) -> str | None:
    """A line-id reference must point at a real kraken line (or be null if allowed)."""
    if line_id is None:
        if allow_none:
            return None
        raise ValueError(f"{ctx} requires a line id, got null")
    line_id = str(line_id)
    if line_id not in valid_ids:
        raise ValueError(f"{ctx} references unknown line {line_id!r}")
    return line_id


def save_review(
    page: int,
    flags: dict[str, int],
    missed: list[dict] | None = None,
    initials: list[dict] | None = None,
    merges: list[dict] | None = None,
    splits: list[dict] | None = None,
    section_titles: list[dict] | None = None,
    status: str = "in_progress",
) -> dict:
    """Persist a page review.

    ``flags`` maps kraken line id -> category number (1/2/3). A line id absent
    from ``flags`` is implicitly "correct"; category 3 = non-text (ignore
    downstream).

    ``missed`` is a list of human-drawn boxes marking lines kraken missed
    entirely: ``[{"id": "missed_001", "box": [x1, y1, x2, y2]}, ...]`` in
    full-resolution page pixels. These have no kraken baseline yet; the later
    integration step synthesizes one (the box's horizontal midline) and merges
    them into reading order via kraken's ``polygonal_reading_order``.

    The remaining args are human correction ops layered on kraken's immutable
    ``lines`` (the corrected geometry is a pure function of these):

    - ``initials``: oversized drop-cap letters the human boxed, each assigned to
      one line: ``{"id", "key", "box":[x1,y1,x2,y2], "target_line_id"}``. The box
      is unioned into ``target_line`` and subtracted from every other line it
      overlaps, so the initial's ink is never duplicated.
    - ``merges``: groups of kraken lines to rejoin: ``{"id", "line_ids":[...]}``.
    - ``splits``: a kraken line to cut vertically: ``{"id", "line_id", "at_x"}``.
    - ``section_titles``: titular section letters: ``{"id", "key",
      "box":[x1,y1,x2,y2], "source_line_id"}`` (source null if drawn fresh).
    """
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status!r}; expected one of {STATUSES}")
    seg = load_segmentation(page)
    valid_ids = {str(line["id"]) for line in seg.get("lines", []) if "id" in line}
    bbox_by_id = {
        str(line["id"]): line.get("bbox")
        for line in seg.get("lines", [])
        if "id" in line
    }

    normalized: dict[str, dict] = {}
    for line_id, category in flags.items():
        category = int(category)
        if category not in CATEGORY_LABELS:
            raise ValueError(f"Unknown category {category!r} for {line_id}")
        normalized[line_id] = {
            "category": category,
            "label": CATEGORY_LABELS[category],
        }

    missed_out: list[dict] = []
    for m in missed or []:
        box = _validate_box(m["box"], f"missed {m.get('id')!r}")
        missed_out.append({"id": str(m["id"]), "box": box})

    initials_out: list[dict] = []
    for it in initials or []:
        ctx = f"initial {it.get('id')!r}"
        initials_out.append({
            "id": str(it["id"]),
            "key": str(it.get("key", "")),
            "box": _validate_box(it["box"], ctx),
            "target_line_id": _validate_line_ref(
                it.get("target_line_id"), valid_ids, ctx, allow_none=True),
        })

    merges_out: list[dict] = []
    for mg in merges or []:
        ctx = f"merge {mg.get('id')!r}"
        line_ids = [_validate_line_ref(lid, valid_ids, ctx, allow_none=False)
                    for lid in mg.get("line_ids", [])]
        if len(line_ids) < 2:
            raise ValueError(f"{ctx} must reference at least 2 lines, got {line_ids!r}")
        merges_out.append({"id": str(mg["id"]), "line_ids": line_ids})

    splits_out: list[dict] = []
    for sp in splits or []:
        ctx = f"split {sp.get('id')!r}"
        line_id = _validate_line_ref(sp.get("line_id"), valid_ids, ctx, allow_none=False)
        at_x = float(sp["at_x"])
        bbox = bbox_by_id.get(line_id)
        if bbox and not (bbox[0] < at_x < bbox[2]):
            raise ValueError(
                f"{ctx} at_x={at_x} outside line x-range [{bbox[0]}, {bbox[2]}]")
        splits_out.append({"id": str(sp["id"]), "line_id": line_id, "at_x": at_x})

    titles_out: list[dict] = []
    for st in section_titles or []:
        ctx = f"section_title {st.get('id')!r}"
        key = str(st.get("key", "")).strip()
        if not key:
            raise ValueError(f"{ctx} requires a non-empty key (the section letter)")
        titles_out.append({
            "id": str(st["id"]),
            "key": key,
            "box": _validate_box(st["box"], ctx),
            "source_line_id": _validate_line_ref(
                st.get("source_line_id"), valid_ids, ctx, allow_none=True),
        })

    record = {
        "page": page,
        "status": status,
        "reviewed_by": "human",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": seg.get("tool", "kraken"),
        "model": seg.get("model"),
        "num_lines": len(seg.get("lines", [])),
        "flags": normalized,
        "missed_lines": missed_out,
        "initials": initials_out,
        "merges": merges_out,
        "splits": splits_out,
        "section_titles": titles_out,
    }
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    review_path(page).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
