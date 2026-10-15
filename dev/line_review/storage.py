"""On-disk state for the Phase 9 review: baseline, review (ops), verified output.

  dev/kraken_review/data/page_<N>/render.png                      page image (shared)
  dev/lineseg_survey/paddle-filled/data/page_<N>/segmentation.json baseline (immutable)
  dev/lineseg_survey/paddle-filled/reviews/page_<N>.review.json    ops + status + ids
  data/verified_lines/page_<N>.json                               materialized on verify

Page status: ``unreviewed`` (no review file) -> ``fixing`` -> ``fixed`` -> ``verified``.
Ops can only change while fixing; Resume fixing returns a fixed or verified page to
fixing. A review records the baseline's sha256: if ``paddle-filled`` is regenerated
under it, the page refuses edits rather than applying ops to renumbered lines.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import materialize as mz
from . import initials
from . import page_number as pn

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_DIR = REPO_ROOT / "dev" / "kraken_review" / "data"
BASELINE_TOOL = "paddle-filled"
BASELINE_DIR = REPO_ROOT / "dev" / "lineseg_survey" / BASELINE_TOOL / "data"
REVIEWS_DIR = REPO_ROOT / "dev" / "lineseg_survey" / BASELINE_TOOL / "reviews"
VERIFIED_DIR = REPO_ROOT / "data" / "verified_lines"
BLANK_DIR = REPO_ROOT / "data" / "pages" / "blank"

SCHEMA = 2
# Printed page number = PDF page - PRINTED_OFFSET throughout the Տօնացոյց (p.458 is
# printed "454"). Only a default for the page-number prompt; a mismatch is flagged.
PRINTED_OFFSET = 4
STATUSES = ("unreviewed", "fixing", "fixed", "verified")
_PAGE_DIR_RE = re.compile(r"^page_(\d+)$")


class StateError(ValueError):
    """An action that the page's current status (or baseline) doesn't allow."""


def render_path(page: int) -> Path:
    return RENDER_DIR / f"page_{page}" / "render.png"


def baseline_path(page: int) -> Path:
    return BASELINE_DIR / f"page_{page}" / "segmentation.json"


def review_path(page: int) -> Path:
    return REVIEWS_DIR / f"page_{page}.review.json"


def verified_path(page: int) -> Path:
    return VERIFIED_DIR / f"page_{page}.json"


def blank_marker(page: int) -> bool:
    path = BLANK_DIR / f"page_{page:04d}.json"
    return path.exists() and bool(json.loads(path.read_text()).get("blank"))


def list_pages() -> list[int]:
    if not BASELINE_DIR.exists():
        return []
    pages = []
    for child in BASELINE_DIR.iterdir():
        m = _PAGE_DIR_RE.match(child.name)
        if m and (child / "segmentation.json").exists():
            pages.append(int(m.group(1)))
    return sorted(pages)


def load_baseline(page: int) -> dict:
    path = baseline_path(page)
    if not path.exists():
        raise FileNotFoundError(f"No baseline for page {page}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def baseline_sha256(page: int) -> str:
    return hashlib.sha256(baseline_path(page).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_review(page: int) -> dict:
    """A page's review before any edit: the page number and initials already marked."""
    ops = auto_ops(page)
    return {
        "schema": SCHEMA, "page": page, "status": "unreviewed",
        "baseline": {"tool": BASELINE_TOOL, "sha256": baseline_sha256(page)},
        "ops": ops, "section_titles": [],
        **mz.empty_id_state(),
        "verified_at": None, "updated_at": None,
    }


def page_image(page: int):
    """The page render as a grayscale array, or None if it isn't there."""
    path = render_path(page)
    if not path.exists():
        return None
    import numpy as np
    from PIL import Image
    return np.array(Image.open(path).convert("L"))


def auto_ops(page: int) -> list[dict]:
    """Ops a fresh review starts with (``"auto": true``): the printed page number, then
    the initials the lines miss. The page-number line is left out of the initial search
    (its bracket is capital-sized). Lines Paddle boxed twice are already gone: the
    materializer drops them (``duplicates``)."""
    seg = load_baseline(page)
    ops = pn.auto_ops(seg, str(page - PRINTED_OFFSET))
    image = page_image(page)
    if image is not None:
        numbered = {op["line"] for op in ops}
        lines = [l for l in mz.materialize_page(mz.baseline_lines(seg), [])["lines"]
                 if l["key"] not in numbered]
        ops += initials.auto_ops(image, lines)
    return ops


def load_review(page: int) -> dict:
    path = review_path(page)
    if not path.exists():
        return new_review(page)
    return json.loads(path.read_text(encoding="utf-8"))


def page_statuses() -> dict[int, str]:
    out = {}
    for page in list_pages():
        path = review_path(page)
        out[page] = json.loads(path.read_text())["status"] if path.exists() else "unreviewed"
    return out


def baseline_changed(review: dict) -> bool:
    return review["baseline"]["sha256"] != baseline_sha256(review["page"])


def _write_review(review: dict) -> dict:
    review["updated_at"] = _now()
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    review_path(review["page"]).write_text(
        json.dumps(review, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return review


def _guard_baseline(review: dict) -> None:
    if baseline_changed(review):
        raise StateError(
            f"page {review['page']}: paddle-filled changed since this review started "
            "(its line ids may have moved); the ops can't be applied safely")


def materialized(page: int, review: dict) -> list[dict]:
    return mz.materialize_page(mz.baseline_lines(load_baseline(page)), review["ops"],
                               review.get("section_titles", []))["lines"]


def save_ops(page: int, ops: list[dict], section_titles: list[dict]) -> tuple[dict, list[dict]]:
    """Replace the page's ops (validated by materializing them); status -> fixing."""
    review = load_review(page)
    _guard_baseline(review)
    if review["status"] not in ("unreviewed", "fixing"):
        raise StateError(f"page {page} is {review['status']}: Resume fixing to edit")
    lines = mz.materialize_page(mz.baseline_lines(load_baseline(page)), ops,
                                section_titles)["lines"]  # raises OpError
    review.update(ops=ops, section_titles=section_titles, status="fixing")
    return _write_review(review), lines


def set_status(page: int, status: str) -> dict:
    """Move the page through fixing -> fixed -> verified (or back to fixing).

    ``verified`` mints line ids and writes ``data/verified_lines/page_<N>.json``.
    """
    review = load_review(page)
    _guard_baseline(review)
    current = review["status"]
    allowed = {
        "fixed": ("unreviewed", "fixing"),
        "verified": ("fixed",),
        "fixing": ("fixed", "verified"),
    }
    if status not in allowed:
        raise StateError(f"unknown target status {status!r}")
    if current not in allowed[status]:
        raise StateError(f"page {page}: can't go from {current} to {status}")

    if status == "verified":
        seg = load_baseline(page)
        lines = materialized(page, review)
        review.update(mz.mint_ids(page, lines, review))
        review["verified_at"] = _now()
        record = mz.verified_record(seg, review, baseline_sha256=baseline_sha256(page))
        VERIFIED_DIR.mkdir(parents=True, exist_ok=True)
        verified_path(page).write_text(mz.dumps(record), encoding="utf-8")
        from . import migrate  # transcriptions typed on this page follow the new ids
        migrate.after_verify(page, lines, review["ids"])
    review["status"] = status
    return _write_review(review)
