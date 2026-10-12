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

Everything else keyed to the page's old keys follows, typed or not, judged against the
line's shape before the verify (the baseline's, or the previous verified output's):
the task's sample picks move to the new id (a split line's to its first part in reading
order; a deleted line's go to ``dropped``); OCR predictions and crops move, or are dropped
for a changed line; a page-level corrector's (``corr-*``) whole page is dropped if any of
its lines changed, since the corrector read the page as a whole.

    uv run python -m dev.line_review.migrate backfill   # fingerprint existing records
    uv run python -m dev.line_review.migrate repair     # pages verified before this existed
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


def before_shapes(page: int, previous_verified: dict | None) -> dict[str, str]:
    """Old key -> ``geometry`` of every line the page's data may still be keyed by: the
    baseline's lines (``p<N>~line_…``) and, on a re-verify, the previous verified ids."""
    from . import materialize as mz
    shapes = {f"p{page}~{l['key']}": tr.geometry(l)
              for l in mz.baseline_lines(storage.load_baseline(page))}
    for l in (previous_verified or {}).get("lines", []):
        shapes[l["id"]] = tr.geometry(l)
    return shapes


def page_map(page: int, page_lines: list[dict], ids: dict[str, str],
             before: dict[str, str]) -> tuple[dict, dict, dict]:
    """How each old key on the page maps to the verified lines.

    Returns (``target``, ``changed``, ``now``): old key -> new id (for a split or merged
    line, the first line made from it; None if deleted); old keys whose line changed
    shape or is gone, with the reason; new id -> geometry of the verified line."""
    by_key = {l["key"]: l for l in page_lines}
    by_id = {ids[l["key"]]: l for l in page_lines}
    now = {ids[l["key"]]: tr.geometry(l) for l in page_lines}
    target, changed = {}, {}
    for old, shape in before.items():
        if lines_mod.is_baseline_key(old):
            key = old.split("~", 1)[1]
            line = by_key.get(key)
        else:
            key, line = None, by_id.get(old)
        if line is not None:
            target[old] = ids[line["key"]]
            if tr.geometry(line) != shape:
                changed[old] = "shape changed"
            continue
        successors = [ids[l["key"]] for l in page_lines if key and key in l.get("lineage", [])]
        target[old] = successors[0] if successors else None
        changed[old] = "line split or merged" if successors else "line removed"
    return target, changed, now


def after_verify(page: int, page_lines: list[dict], ids: dict[str, str],
                 before: dict[str, str] | None = None) -> dict:
    """Re-key every task's transcriptions, sample picks, predictions and crops on ``page``
    to its verified ids. ``before``: see ``before_shapes`` (computed if None)."""
    if before is None:
        before = before_shapes(page, None)
    target, changed, now = page_map(page, page_lines, ids, before)
    summary = {}
    for task in _tasks():
        moved, stale = _move_records(page, task, target, changed, now)
        picks = _move_picks(task, target, changed)
        preds = _move_predictions(task, page, target, changed)
        if moved or stale or picks or preds:
            summary[task] = {"moved": moved, "stale": stale, "picks": picks, "predictions": preds}
    return summary


def _move_records(page: int, task: str, target: dict, changed: dict, now: dict) -> tuple[int, dict]:
    """A record moves to its line's new id if the line still has the shape it was typed
    against (its ``geometry``; without one, the shape before verify); else it goes stale."""
    records = tr.load_page(page, task)
    moved, stale = 0, {}
    for rid in list(records):
        new = target.get(rid, rid if rid in now else None)
        if new is None and rid not in target:
            continue  # not a line of this page's layout (shouldn't happen)
        rec = records[rid]
        same = (rec["geometry"] == now.get(new)) if "geometry" in rec else rid not in changed
        if new is not None and same:
            if new != rid:
                records[new] = {**records.pop(rid), "migrated_from": rid}
                moved += 1
            continue
        why = changed.get(rid) or "shape changed"
        stale[rid] = why
        path = _stale_path(page, task)
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        old.append({"id": rid, "reason": why, "replaced_by": new, "at": _now(), "record": records.pop(rid)})
        _write_json(path, old)
    if moved or stale:
        tr._write_page(page, task, records)
    return moved, stale


def _move_picks(task: str, target: dict, changed: dict) -> int:
    if not tr.sample_path(task).exists():
        return 0
    sample = tr.load_sample(task)
    picks, dropped, n = [], sample.get("dropped", []), 0
    for p in sample["picks"]:
        new = target.get(p["id"], p["id"])
        if new is None:
            dropped.append({**p, "reason": changed[p["id"]], "at": _now()})
            n += 1
            continue
        if new != p["id"]:
            p = {**p, "id": new, "was": p["id"]}
            n += 1
        picks.append(p)
    if n:
        sample["picks"] = picks
        if dropped:
            sample["dropped"] = dropped
        tr.save_sample(sample, task)
    return n


def _move_predictions(task: str, page: int, target: dict, changed: dict) -> int:
    """Re-key predictions of unchanged lines; drop those of changed lines, and a page-level
    corrector's (``corr-*``) whole page if any of its lines changed."""
    pred_dir = PREDICTIONS_DIR / task
    n = 0
    if pred_dir.is_dir():
        prefix = (f"p{page}~", f"p{page}.")
        for path in sorted(pred_dir.glob("*.json")):
            rec = json.loads(path.read_text(encoding="utf-8"))
            preds = rec.get("lines", {})
            on_page = [k for k in preds if k.startswith(prefix)]
            if path.stem.startswith("corr-") and any(k in changed for k in on_page):
                new = {k: v for k, v in preds.items() if not k.startswith(prefix)}
            else:
                new = {}
                for k, v in preds.items():
                    if k in changed:
                        continue
                    nk = target.get(k, k)
                    new[nk if nk is not None else k] = v
            if new != preds:
                rec["lines"] = dict(sorted(new.items()))
                _write_json(path, rec)
                n += 1
    crops = CROPS_DIR / f"{task}_crops"
    if crops.is_dir():
        for old, new in target.items():
            src = crops / f"{old}.png"
            if not src.exists():
                continue
            if old in changed or new is None:
                src.unlink()
            elif new != old and not (crops / f"{new}.png").exists():
                src.rename(crops / f"{new}.png")
    return n


def repair() -> None:
    """Re-key data left on baseline keys of pages already verified (e.g. verified before
    this module existed). Idempotent."""
    for page in storage.list_pages():
        review = storage.load_review(page)
        if review["status"] != "verified":
            continue
        lines = storage.materialized(page, review)
        summary = after_verify(page, lines, review["ids"])
        if summary:
            print(f"p{page}: {summary}")


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
    ap.add_argument("step", choices=["backfill", "repair"])
    {"backfill": backfill, "repair": repair}[ap.parse_args().step]()


if __name__ == "__main__":
    main()
