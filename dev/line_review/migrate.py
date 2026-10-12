"""Carry transcriptions over when a page is verified (Phase 9 → Phases 10/11).

The ceiling sample (``dev/ocr_eval/ceiling.py``) was typed on pages not yet verified,
keyed by baseline keys (``p520~line_013``). Verifying a page mints permanent ids
(``p520.013``), and the app then looks the page's lines up by id, so without this step
those transcriptions would stop matching any line.

Each transcription stores ``geometry``, a fingerprint of the line shape it was typed
against (``transcribe.geometry``). On verify, for each task's records on the page:

- **same shape**: a baseline-keyed record moves to the line's new id (``migrated_from``
  records the old key); a record already keyed by id stays.
- **shape changed, or the line is gone** (reshaped, split, merged, deleted): the record
  moves to ``data/transcriptions/<task>/stale/page_<N>.json`` with the reason, and the line
  shows as untyped so it can be retyped (the stale text can serve as a prefill).

The task's sample (``sample.json``) follows: a pick moves to the new id, a split line's pick
to its first part in reading order, and a deleted line's pick goes to ``dropped``. OCR
predictions keyed by baseline key (``data/ocr_predictions/<task>/``) move the same way;
a changed line's predictions are dropped, and a page-level corrector's (``corr-*``) whole
page is dropped if any of its lines changed, since the corrector read the page as a whole.

    uv run python -m dev.line_review.migrate backfill   # fingerprint existing records
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from . import lines as lines_mod
from . import storage
from . import transcribe as tr

PREDICTIONS_DIR = storage.REPO_ROOT / "data" / "ocr_predictions"
CROPS_DIR = storage.REPO_ROOT / "runs" / "ocr_eval"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tasks() -> list[str]:
    root = tr.TRANSCRIPTIONS_DIR
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []


def _stale_path(page: int, task: str):
    return tr.TRANSCRIPTIONS_DIR / task / "stale" / f"page_{page}.json"


def _write_json(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def plan(page: int, page_lines: list[dict], ids: dict[str, str], records: dict) -> tuple[dict, dict]:
    """(moves, stale) for one task's records on a just-verified page.

    ``page_lines`` are the materialized lines (with ``key`` and ``lineage``), ``ids`` the
    key → id map minted on verify. ``moves``: record id → new id (same shape).
    ``stale``: record id → (reason, id of the line that replaces it, or None)."""
    by_key = {l["key"]: l for l in page_lines}
    by_id = {ids[l["key"]]: l for l in page_lines}
    moves, stale = {}, {}
    for rid, rec in records.items():
        if lines_mod.is_baseline_key(rid):
            key = rid.split("~", 1)[1]
            line = by_key.get(key)
            successors = [ids[l["key"]] for l in page_lines if key in l.get("lineage", [])]
        else:
            line = by_id.get(rid)
            successors = []
        if line is None:
            stale[rid] = ("line removed" if not successors else "line split or merged",
                          successors[0] if successors else None)
            continue
        new = ids[line["key"]]
        if rec.get("geometry") != tr.geometry(line):
            stale[rid] = ("shape changed" if "geometry" in rec else "shape not recorded", new)
        elif new != rid:
            moves[rid] = new
    return moves, stale


def after_verify(page: int, page_lines: list[dict], ids: dict[str, str]) -> dict:
    """Migrate every task's transcriptions, sample and predictions on ``page``."""
    summary = {}
    for task in _tasks():
        records = tr.load_page(page, task)
        if not records:
            continue
        moves, stale = plan(page, page_lines, ids, records)
        if not moves and not stale:
            continue
        for rid, new in moves.items():
            records[new] = {**records.pop(rid), "migrated_from": rid}
        if stale:
            path = _stale_path(page, task)
            old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            old += [{"id": rid, "reason": why, "replaced_by": rep, "at": _now(), **{"record": records.pop(rid)}}
                    for rid, (why, rep) in stale.items()]
            _write_json(path, old)
        tr._write_page(page, task, records)
        _move_picks(task, moves, stale)
        _move_predictions(task, page, moves, stale)
        summary[task] = {"moved": len(moves), "stale": {r: w for r, (w, _) in stale.items()}}
    return summary


def _move_picks(task: str, moves: dict, stale: dict) -> None:
    if not tr.sample_path(task).exists():
        return
    sample = tr.load_sample(task)
    picks, dropped = [], sample.get("dropped", [])
    for p in sample["picks"]:
        if p["id"] in moves:
            p = {**p, "id": moves[p["id"]], "was": p["id"]}
        elif p["id"] in stale:
            why, rep = stale[p["id"]]
            if rep is None:
                dropped.append({**p, "reason": why, "at": _now()})
                continue
            if rep != p["id"]:
                p = {**p, "id": rep, "was": p["id"]}
        picks.append(p)
    sample["picks"] = picks
    if dropped:
        sample["dropped"] = dropped
    tr.save_sample(sample, task)


def _move_predictions(task: str, page: int, moves: dict, stale: dict) -> None:
    pred_dir = PREDICTIONS_DIR / task
    if not pred_dir.is_dir():
        return
    prefix = (f"p{page}~", f"p{page}.")
    for path in sorted(pred_dir.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        preds = rec.get("lines", {})
        page_level = path.stem.startswith("corr-")
        if page_level and stale and any(k.startswith(prefix) for k in preds):
            new = {k: v for k, v in preds.items() if not k.startswith(prefix)}
        else:
            new = {}
            for k, v in preds.items():
                if k in stale:
                    continue
                new[moves.get(k, k)] = v
        if new != preds:
            rec["lines"] = dict(sorted(new.items()))
            _write_json(path, rec)
    crops = CROPS_DIR / f"{task}_crops"
    for old, new in moves.items():
        src, dst = crops / f"{old}.png", crops / f"{new}.png"
        if src.exists() and not dst.exists():
            src.rename(dst)
    for old in stale:
        (crops / f"{old}.png").unlink(missing_ok=True)


def backfill() -> None:
    """Fingerprint records typed before ``geometry`` was stored, from the line as it is
    now. Pages are assumed unchanged since typing; any page reviewed since is listed."""
    for task in _tasks():
        n, missing = 0, []
        for path in sorted((tr.TRANSCRIPTIONS_DIR / task).glob("page_*.json")):
            page = int(path.stem.split("_")[1])
            records = tr.load_page(page, task)
            changed = False
            for rid, rec in records.items():
                if "geometry" in rec:
                    continue
                try:
                    line, _ = lines_mod.find(rid)
                except KeyError:
                    missing.append(rid)
                    continue
                rec["geometry"] = tr.geometry(line)
                changed, n = True, n + 1
            if changed:
                tr._write_page(page, task, records)
        print(f"{task}: {n} records fingerprinted" + (f"; not found: {missing}" if missing else ""))
    statuses = storage.page_statuses()
    edited = sorted(p for p in {int(f.stem.split("_")[1]) for t in _tasks()
                                for f in (tr.TRANSCRIPTIONS_DIR / t).glob("page_*.json")}
                    if statuses.get(p) in ("fixing", "fixed"))
    if edited:
        print(f"pages under review now (check their lines weren't edited after typing): {edited}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["backfill"])
    ap.parse_args()
    backfill()


if __name__ == "__main__":
    main()
