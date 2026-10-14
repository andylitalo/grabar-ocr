"""Line transcriptions keyed by verified line id (Phase 10, docs/phase_10_ocr_test_set.md).

Two parts, both general beyond the test set:

- **Transcriptions** live per *task* in ``data/transcriptions/<task>/page_<N>.json``:
  ``{line_id: {text, status, at, by, prefill, geometry, recheck?}}``. The test set is task
  ``testset`` and is typed blank (``prefill`` None). A later task where contributors
  correct OCR predictions uses the same records with ``prefill = {engine, text}``.
- **The test-set sample**: a stratified, append-only pick of verified lines
  (``data/transcriptions/testset/sample.json``), topped up as more pages are verified.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPTIONS_DIR = REPO_ROOT / "data" / "transcriptions"
TESTSET = "testset"

STATUSES = ("done", "illegible", "bad-crop")
VOL1 = range(453, 552)      # PDF pages; Vol II is 553-643 (corpus/STRUCTURE.md)
EXCLUDED_PAGES = {641}      # the Paschal table: cells, not lines
DISPLAY_RATIO = 1.4         # line height / page median height for display type
QUOTAS = {"vol1-body": 110, "vol2-body": 110, "display": 50, "drop-cap": 30}
# Max picks per stratum per page, so each stratum spreads through the book as pages are
# verified instead of filling from the first pages (or one stratum crowding out another).
PER_PAGE = {"vol1-body": 2, "vol2-body": 2, "display": 1, "drop-cap": 1}
SEED = "phase10-2026-10-04"
RECHECK_EVERY, RECHECK_CAP = 10, 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def page_of(line_id: str) -> int:
    """``p457.023`` -> 457; also baseline keys, ``p520~line_013`` -> 520."""
    return int(line_id[1:].split("~")[0].split(".")[0])


# --- sample ----------------------------------------------------------------------


def stratum(line: dict, page: int, median_height: float) -> str:
    if line.get("initial"):
        return "drop-cap"
    if line["bbox"][3] - line["bbox"][1] >= DISPLAY_RATIO * median_height:
        return "display"
    return "vol1-body" if page in VOL1 else "vol2-body"


def candidates(verified_pages: list[dict]) -> list[dict]:
    """Every verified line eligible for the sample, with its stratum."""
    out = []
    for rec in verified_pages:
        page = rec["page"]
        if page in EXCLUDED_PAGES or not rec["lines"]:
            continue
        median = statistics.median(l["bbox"][3] - l["bbox"][1] for l in rec["lines"])
        out += [{"id": l["id"], "page": page, "stratum": stratum(l, page, median)}
                for l in rec["lines"]]
    return out


def rank(seed: str, line_id: str) -> str:
    return hashlib.sha256(f"{seed}:{line_id}".encode()).hexdigest()


def new_sample(seed: str = SEED, quotas: dict | None = None, per_page: dict | None = None) -> dict:
    return {"seed": seed, "quotas": dict(quotas or QUOTAS),
            "per_page": dict(per_page or PER_PAGE), "picks": []}


def top_up(sample: dict, pool: list[dict]) -> dict:
    """Fill each stratum's unfilled quota with its lowest-ranked unpicked lines.

    Append-only: existing picks never move, even if their line has since been retired
    (``missing_picks`` reports those).
    """
    picks = list(sample["picks"])
    taken = {p["id"] for p in picks}
    caps = sample.get("per_page", PER_PAGE)
    used: dict[tuple[str, int], int] = {}
    for p in picks:
        used[p["stratum"], p["page"]] = used.get((p["stratum"], p["page"]), 0) + 1
    for name, quota in sample["quotas"].items():
        need = quota - sum(p["stratum"] == name for p in picks)
        fresh = sorted((c for c in pool if c["stratum"] == name and c["id"] not in taken),
                       key=lambda c: rank(sample["seed"], c["id"]))
        for c in fresh:
            if need <= 0:
                break
            if used.get((name, c["page"]), 0) >= caps.get(name, 1):
                continue
            picks.append({"id": c["id"], "stratum": name, "page": c["page"]})
            taken.add(c["id"])
            used[name, c["page"]] = used.get((name, c["page"]), 0) + 1
            need -= 1
    return {**sample, "picks": picks}


def missing_picks(sample: dict, pool: list[dict]) -> list[str]:
    """Picked ids no longer among the verified lines (e.g. split on re-verification)."""
    live = {c["id"] for c in pool}
    return [p["id"] for p in sample["picks"] if p["id"] not in live]


def recheck_ids(sample: dict, every: int = RECHECK_EVERY, cap: int = RECHECK_CAP) -> list[str]:
    """Picks queued for the blind second pass: about 1 in ``every``, at most ``cap``."""
    chosen = [p["id"] for p in sample["picks"]
              if int(rank(sample["seed"] + ":recheck", p["id"]), 16) % every == 0]
    return chosen[:cap]


def sample_path(task: str = TESTSET) -> Path:
    return TRANSCRIPTIONS_DIR / task / "sample.json"


def load_sample(task: str = TESTSET) -> dict:
    path = sample_path(task)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else new_sample()


def save_sample(sample: dict, task: str = TESTSET) -> None:
    sample_path(task).parent.mkdir(parents=True, exist_ok=True)
    sample_path(task).write_text(json.dumps(sample, indent=1, ensure_ascii=False) + "\n",
                                 encoding="utf-8")


# --- transcriptions --------------------------------------------------------------


def _page_path(page: int, task: str) -> Path:
    return TRANSCRIPTIONS_DIR / task / f"page_{page}.json"


def load_page(page: int, task: str = TESTSET) -> dict:
    path = _page_path(page, task)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_page(page: int, task: str, records: dict) -> None:
    path = _page_path(page, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(records.items())), indent=1, ensure_ascii=False)
                    + "\n", encoding="utf-8")


def load_line(line_id: str, task: str = TESTSET) -> dict | None:
    return load_page(page_of(line_id), task).get(line_id)


def effective_line(key: str, task: str) -> dict | None:
    """``key``'s transcription for ``task``: its own, else (for a verified line id) one
    already typed for the test set, so no line is typed twice."""
    rec = load_line(key, task)
    if rec is None and task != TESTSET and "~" not in key:
        rec = load_line(key, TESTSET)
    return rec


def geometry(line: dict) -> str:
    """Fingerprint of the line shape a transcription was typed against, so a later edit
    of the shape can be detected (``dev/line_review/migrate.py``)."""
    pts = [[round(x), round(y)] for x, y in line["boundary"]]
    return hashlib.sha256(json.dumps(pts).encode()).hexdigest()[:16]


def save_line(line_id: str, *, text: str, status: str, task: str = TESTSET,
              by: str = "maintainer", prefill: dict | None = None,
              geometry: str | None = None) -> dict:
    """Store one line's transcription (replacing an earlier one, keeping its recheck).
    ``geometry``: ``geometry(line)`` of the line as shown when it was typed."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")
    page = page_of(line_id)
    records = load_page(page, task)
    rec = {"text": text, "status": status, "at": _now(), "by": by, "prefill": prefill}
    if geometry is not None:
        rec["geometry"] = geometry
    if "recheck" in records.get(line_id, {}):
        rec["recheck"] = records[line_id]["recheck"]
    records[line_id] = rec
    _write_page(page, task, records)
    return rec


def save_recheck(line_id: str, *, text: str, task: str = TESTSET, by: str = "maintainer") -> dict:
    """Store the blind second pass for a line already transcribed."""
    page = page_of(line_id)
    records = load_page(page, task)
    if line_id not in records:
        raise ValueError(f"{line_id} has no first transcription to recheck")
    records[line_id]["recheck"] = {"text": text, "at": _now(), "by": by}
    _write_page(page, task, records)
    return records[line_id]
