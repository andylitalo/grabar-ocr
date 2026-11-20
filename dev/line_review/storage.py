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
tab, or a stale client) is refused rather than overwriting newer ops. Saves and status
changes on a page hold that page's lock from the revision check to the write (the app
serves requests on a thread pool), and every file is written to a temp file and renamed
into place, so a crash mid-write leaves the old file, never a truncated one.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import cv2

from . import materialize as mz
from . import page_number as pn
from . import unclip

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


# path -> ((mtime_ns, size), bytes, sha256): each request used to read and hash the
# baseline 3-4 times. Re-read whenever the file changes on disk.
_baseline_cache: dict[Path, tuple[tuple[int, int], bytes, str]] = {}


def _baseline_bytes(page: int) -> tuple[bytes, str]:
    path = baseline_path(page)
    if not path.exists():
        raise FileNotFoundError(f"No baseline for page {page}: {path}")
    st = path.stat()
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _baseline_cache.get(path)
    if hit is None or hit[0] != stamp:
        data = path.read_bytes()
        hit = (stamp, data, hashlib.sha256(data).hexdigest())
        _baseline_cache[path] = hit
    return hit[1], hit[2]


def load_baseline(page: int) -> dict:
    return json.loads(_baseline_bytes(page)[0].decode("utf-8"))


def baseline_sha256(page: int) -> str:
    return _baseline_bytes(page)[1]


def baseline_manifest() -> dict[int, str]:
    """The committed sha256 of each baseline page (empty if there is no manifest)."""
    if not MANIFEST_PATH.exists():
        return {}
    return {int(k): v for k, v in json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).items()}


def current_baseline_hashes() -> dict[int, str]:
    return {page: baseline_sha256(page) for page in list_pages()}


def write_manifest(hashes: dict[int, str]) -> None:
    write_atomic(MANIFEST_PATH, json.dumps({str(p): h for p, h in sorted(hashes.items())},
                                           indent=1) + "\n")


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file and a rename, so readers (and a crash)
    see the old file or the new one, never a partial one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


@contextmanager
def page_lock(page: int) -> Iterator[None]:
    """Hold ``page``'s lock: one load-check-write at a time per page."""
    with _locks_guard:
        lock = _locks.setdefault(page, threading.Lock())
    with lock:
        yield


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def expected_page_number(page: int) -> str:
    """The number printed on PDF page ``page`` (PDF page - PRINTED_OFFSET)."""
    return str(page - PRINTED_OFFSET)


# (page, baseline sha256, render mtime) -> the unclip ops of a fresh review. They read the
# page image, and an unreviewed page is loaded on every visit and by the OCR side's
# page_lines. At most one entry per page (~50 ops), so it isn't bounded.
_unclip_cache: dict[tuple[int, str, int | None], list[dict]] = {}
log = logging.getLogger(__name__)


def _unclip_ops(page: int, ops: list[dict]) -> list[dict]:
    """``unclip.auto_ops`` on the page as ``ops`` leave it; none without a page render
    (the review app can't show such a page anyway)."""
    path = render_path(page)
    key = (page, baseline_sha256(page), path.stat().st_mtime_ns if path.exists() else None)
    if key not in _unclip_cache:
        if not path.exists():
            log.warning("p%d: no page render at %s, so its fresh review starts without the "
                        "unclip reshapes (boxes as Paddle cut them)", page, path)
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path.exists() else None
        # Not through the page cache: the result is kept above, and these ops (before the
        # unclip reshapes) aren't what the reviewer's requests look up.
        lines = materialized_page(page, ops, [], cache=False)["lines"] if gray is not None else []
        _unclip_cache[key] = unclip.auto_ops(lines, gray) if lines else []
    return copy.deepcopy(_unclip_cache[key])


def new_review(page: int) -> dict:
    """A page's review before any edit: the printed page number already marked, when the
    top line looks like one (``page_number.detect``), then every box pushed out over the
    letters it cuts (``unclip``). The reviewer can remove either."""
    ops = pn.auto_ops(load_baseline(page), expected_page_number(page))
    ops += _unclip_ops(page, ops)
    return {
        "schema": SCHEMA, "page": page, "status": "unreviewed",
        "baseline": {"tool": BASELINE_TOOL, "sha256": baseline_sha256(page)},
        "ops": ops, "section_titles": [],
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
    write_atomic(review_path(review["page"]), dumps_review(review))
    return review


def dumps_review(review: dict) -> str:
    """The review as JSON: one op per line (a reshape's polygon inline, so a review stays
    diff-friendly; see "Data storage" in AGENTS.md), every other field as ``indent=1``."""
    def field(k, v) -> str:
        if k == "ops" and v:
            body = ",\n".join("  " + json.dumps(op, ensure_ascii=False) for op in v)
            return f'"ops": [\n{body}\n ]'
        return f"{json.dumps(k)}: " + json.dumps(v, indent=1, ensure_ascii=False).replace("\n", "\n ")
    return "{\n " + ",\n ".join(field(k, v) for k, v in review.items()) + "\n}\n"


def _guard_baseline(review: dict) -> None:
    if baseline_changed(review):
        raise StateError(
            f"page {review['page']}: paddle-filled changed since this review started "
            "(its line ids may have moved); the ops can't be applied safely")


# (baseline sha256, ops, titles) -> materialized page. A save or verify, and the page it
# sends back, would otherwise each re-run the shapely ops and the O(n^2) duplicate checks.
_page_cache: dict[tuple[str, str], dict] = {}
_PAGE_CACHE_SIZE = 16


def materialized_page(page: int, ops: list[dict], section_titles: list[dict],
                      cache: bool = True) -> dict:
    """``mz.materialize_page`` of the page's baseline (a copy; safe to change).

    The cache is shared by the request threads and ``overlap.warm``, so each access is one
    dict operation: the page is looked up once and the thread works from its own reference,
    and evicting tolerates an entry another thread evicted first. Another thread can then
    only cost a recompute, never a ``KeyError``. ``cache=False`` neither reads nor fills
    it (``overlap.warm``, which goes through every page, would push out the reviewer's)."""
    key = (baseline_sha256(page), json.dumps([ops, section_titles], sort_keys=True))
    result = _page_cache.get(key) if cache else None
    if result is None:
        result = mz.materialize_page(mz.baseline_lines(load_baseline(page)), ops,
                                     section_titles)  # raises OpError (not cached)
        if cache:
            if len(_page_cache) >= _PAGE_CACHE_SIZE:
                _page_cache.pop(next(iter(_page_cache), None), None)
            _page_cache[key] = result
    return copy.deepcopy(result)


def materialized(page: int, review: dict, cache: bool = True) -> list[dict]:
    return materialized_page(page, review["ops"], review.get("section_titles", []),
                             cache=cache)["lines"]


def save_ops(page: int, ops: list[dict], section_titles: list[dict],
             revision: int | None = None) -> tuple[dict, list[dict]]:
    """Replace the page's ops (validated by materializing them); status -> fixing.

    ``revision``: the review revision the client's ops were built on (None skips the check).
    """
    with page_lock(page):
        review = load_review(page)
        _guard_baseline(review)
        _check_revision(review, revision)
        if review["status"] not in ("unreviewed", "fixing"):
            raise StateError(f"page {page} is {review['status']}: Resume fixing to edit")
        add_keys = _check_add_keys(review, ops)  # raises OpError
        lines = materialized_page(page, ops, section_titles)["lines"]  # raises OpError
        review.update(ops=ops, section_titles=section_titles, status="fixing", add_keys=add_keys)
        return _write_review(review), lines


def _mark_resumed(page: int) -> None:
    """Flag the page's verified file as out of date without deleting it: readers skip it
    while the review isn't ``verified``, and the next verify rewrites it whole."""
    path = verified_path(page)
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        record["resumed_at"] = _now()
        write_atomic(path, mz.dumps(record))


def set_status(page: int, status: str, revision: int | None = None) -> dict:
    """Move the page through fixing -> fixed -> verified (or back to fixing).

    ``verified`` mints line ids and writes ``data/verified_lines/page_<N>.json``;
    verified -> fixing marks that file ``resumed_at``.
    """
    with page_lock(page):
        return _set_status(page, status, revision)


def _set_status(page: int, status: str, revision: int | None) -> dict:
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
        page_el = materialized_page(page, review["ops"], review.get("section_titles", []))
        review.update(mz.mint_ids(page, page_el["lines"], review))
        review["verified_at"] = _now()
        record = mz.verified_record(load_baseline(page), review,
                                    baseline_sha256=baseline_sha256(page), page_el=page_el)
        # Transcriptions, picks and predictions keyed to the old line keys are not moved
        # here: `python -m dev.line_review.migrate repair` moves them, with each batch's
        # data PR and once after the layout review (dev/line_review/migrate.py).
        write_atomic(verified_path(page), mz.dumps(record))
    elif current == "verified":
        _mark_resumed(page)
    review["status"] = status
    return _write_review(review)
