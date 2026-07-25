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

# category number -> human label; the single source of truth for the taxonomy.
CATEGORY_LABELS = {
    1: "over-segmentation",
    2: "under-segmentation",
    3: "non-text",
}

_PAGE_DIR_RE = re.compile(r"^page_(\d+)$")


def data_dir(page: int) -> Path:
    return DATA_DIR / f"page_{page}"


def render_path(page: int) -> Path:
    return data_dir(page) / "render.png"


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


def load_segmentation(page: int) -> dict:
    path = segmentation_path(page)
    if not path.exists():
        raise FileNotFoundError(f"No segmentation for page {page}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_review(page: int) -> dict:
    """Existing review for a page, or an empty skeleton if none saved yet."""
    path = review_path(page)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("flags", {})
        data.setdefault("missed_lines", [])
        return data
    return {"page": page, "flags": {}, "missed_lines": []}


def save_review(page: int, flags: dict[str, int], missed: list[dict] | None = None) -> dict:
    """Persist a page review.

    ``flags`` maps kraken line id -> category number (1/2/3). A line id absent
    from ``flags`` is implicitly "correct"; category 3 = non-text (ignore
    downstream).

    ``missed`` is a list of human-drawn boxes marking lines kraken missed
    entirely: ``[{"id": "missed_001", "box": [x1, y1, x2, y2]}, ...]`` in
    full-resolution page pixels. These have no kraken baseline yet; the later
    integration step synthesizes one (the box's horizontal midline) and merges
    them into reading order via kraken's ``polygonal_reading_order``.
    """
    seg = load_segmentation(page)
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
        box = [float(v) for v in m["box"]]
        if len(box) != 4:
            raise ValueError(f"missed box must have 4 coords [x1,y1,x2,y2], got {m['box']!r}")
        missed_out.append({"id": str(m["id"]), "box": box})

    record = {
        "page": page,
        "reviewed_by": "human",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": seg.get("model"),
        "num_lines": len(seg.get("lines", [])),
        "flags": normalized,
        "missed_lines": missed_out,
    }
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    review_path(page).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
