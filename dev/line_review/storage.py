"""On-disk state for the Phase 9 review: baseline, review (ops), verified output.

  dev/kraken_review/data/page_<N>/render.png                      page image (shared)
  data/lineseg_survey/paddle-filled/pages/page_<N>/segmentation.json baseline (immutable)
  data/lineseg_survey/paddle-filled/reviews/page_<N>.review.json    ops + status + ids
  data/verified_lines/page_<N>.json                               materialized on verify

  data/lineseg_survey/paddle-filled/baseline_sha256.json            sha256 of every baseline page

Page status: ``unreviewed`` (no review file) -> ``fixing`` -> ``fixed`` -> ``verified``.
Ops can only change while fixing; Resume fixing returns a fixed or verified page to
fixing, and marks its verified file ``resumed_at`` (kept, not deleted, until the page is
verified again and the file is rewritten whole). A review records the baseline's sha256:
if ``paddle-filled`` is regenerated under it, the page refuses edits rather than applying
ops to renumbered lines. ``baseline_sha256.json`` covers the pages not reviewed yet.

Every write bumps the review's ``revision``; a save that names an older revision (another
tab, or a stale client) is refused rather than overwriting newer ops.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import materialize as mz

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_DIR = REPO_ROOT / "dev" / "kraken_review" / "data"
BASELINE_TOOL = "paddle-filled"
BASELINE_DIR = REPO_ROOT / "data" / "lineseg_survey" / BASELINE_TOOL / "pages"
REVIEWS_DIR = REPO_ROOT / "data" / "lineseg_survey" / BASELINE_TOOL / "reviews"
VERIFIED_DIR = REPO_ROOT / "data" / "verified_lines"
MANIFEST_PATH = REPO_ROOT / "data" / "lineseg_survey" / BASELINE_TOOL / "baseline_sha256.json"
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


def baseline_manifest() -> dict[int, str]:
    """The committed sha256 of each baseline page (empty if there is no manifest)."""
    if not MANIFEST_PATH.exists():
        return {}
    return {int(k): v for k, v in json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).items()}


def current_baseline_hashes() -> dict[int, str]:
    return {page: baseline_sha256(page) for page in list_pages()}


def write_manifest(hashes: dict[int, str]) -> None:
    MANIFEST_PATH.write_text(json.dumps({str(p): h for p, h in sorted(hashes.items())},
                                        indent=1) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_review(page: int) -> dict:
    return {
        "schema": SCHEMA, "page": page, "status": "unreviewed",
        "baseline": {"tool": BASELINE_TOOL, "sha256": baseline_sha256(page)},
        "ops": [], "section_titles": [],
        **mz.empty_id_state(),
        "verified_at": None, "updated_at": None,
    }


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


def used_add_keys(review: dict) -> dict[str, list | None]:
    """Every ``add`` key the page has used -> the boundary it was added with (None if
    only known from minted ids). A key is never handed to a different box."""
    used: dict[str, list | None] = {k: None for k in [*review.get("ids", {}),
                                                    *review.get("retired_keys", {})]
                                    if k.startswith("add_")}
    used.update(review.get("add_keys", {}))
    for op in review.get("ops", []):
        if op.get("op") == "add" and used.get(op["key"]) is None:
            used[op["key"]] = op.get("boundary")
    return used


def _check_add_keys(review: dict, ops: list[dict]) -> dict[str, list | None]:
    used = used_add_keys(review)
    for op in ops:
        if op.get("op") != "add":
            continue
        key = op.get("key")
        if key in used and used[key] != op.get("boundary"):
            raise mz.OpError(f"add key {key!r} was already used for another box on this "
                             "page; added lines need a new key")
        used[key] = op.get("boundary")
    return used


def _check_revision(review: dict, revision: int | None) -> None:
    if revision is not None and revision != review.get("revision", 0):
        raise StateError(f"page {review['page']} was saved elsewhere since this view loaded "
                         f"(revision {review.get('revision', 0)}, not {revision}); reload it")


def baseline_changed(review: dict) -> bool:
    return review["baseline"]["sha256"] != baseline_sha256(review["page"])


def _write_review(review: dict) -> dict:
    review["updated_at"] = _now()
    review["revision"] = review.get("revision", 0) + 1
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


def save_ops(page: int, ops: list[dict], section_titles: list[dict],
             revision: int | None = None) -> tuple[dict, list[dict]]:
    """Replace the page's ops (validated by materializing them); status -> fixing.

    ``revision``: the review revision the client's ops were built on (None skips the check).
    """
    review = load_review(page)
    _guard_baseline(review)
    _check_revision(review, revision)
    if review["status"] not in ("unreviewed", "fixing"):
        raise StateError(f"page {page} is {review['status']}: Resume fixing to edit")
    add_keys = _check_add_keys(review, ops)  # raises OpError
    lines = mz.materialize_page(mz.baseline_lines(load_baseline(page)), ops,
                                section_titles)["lines"]  # raises OpError
    review.update(ops=ops, section_titles=section_titles, status="fixing", add_keys=add_keys)
    return _write_review(review), lines


def _mark_resumed(page: int) -> None:
    """Flag the page's verified file as out of date without deleting it: readers skip it
    while the review isn't ``verified``, and the next verify rewrites it whole."""
    path = verified_path(page)
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        record["resumed_at"] = _now()
        path.write_text(mz.dumps(record), encoding="utf-8")


def set_status(page: int, status: str, revision: int | None = None) -> dict:
    """Move the page through fixing -> fixed -> verified (or back to fixing).

    ``verified`` mints line ids and writes ``data/verified_lines/page_<N>.json``;
    verified -> fixing marks that file ``resumed_at``.
    """
    review = load_review(page)
    _guard_baseline(review)
    _check_revision(review, revision)
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
    elif current == "verified":
        _mark_resumed(page)
    review["status"] = status
    return _write_review(review)
