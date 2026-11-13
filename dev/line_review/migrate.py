"""Carry transcriptions over to verified line ids (Phase 9 → Phases 10/11).

The ceiling sample (``dev/ocr_eval/ceiling.py``) was typed on pages not yet verified,
keyed by baseline keys (``p520~line_013``). Verifying a page mints permanent ids
(``p520.013``), and the app then looks the page's lines up by id, so without this step
those transcriptions would stop matching any line.

**When it runs:** once, after the whole layout review (``repair`` below), not on each
verify. No transcription or OCR runs while pages are being reviewed, so moving the data
once, from pages whose ids are already saved, can't race an edit or an OCR run, and a
repair that fails partway is simply run again (docs/phase_9_line_segmentation_review.md).

Each transcription stores ``geometry``, a fingerprint of the line shape it was typed
against (``transcribe.geometry``). For each task's records on the page:

- **same shape**: a baseline-keyed record moves to the line's new id (``migrated_from``
  records the old key); a record already keyed by id stays.
- **shape changed, or the line is gone** (reshaped, split, merged, deleted): the record
  moves to ``data/transcriptions/<task>/stale/page_<N>.json`` with the reason, and the line
  shows as untyped so it can be retyped (the stale text can serve as a prefill).

Everything else keyed to the page's old keys follows, typed or not, judged against the
line's shape before the review: the baseline's (crops are exported once per key, so a
baseline key's crop and predictions are of its baseline shape), or the previous verified
output's when it is given. A key only the ops made (``add_…``, ``…/1``, ``…+…``) has no
known earlier shape, so its predictions and crop are dropped (the engines re-run on it);
its transcription is still judged by its own ``geometry`` and its pick still follows.
Every key the page's data uses is mapped, so a line removed before the verify sends its
transcription to ``stale/`` and its pick to ``dropped`` instead of leaving them behind.
The task's sample picks move to the new id (a split or merged line's to
its first successor in reading order, found through the line's lineage, or through
``superseded_by`` for a retired id; a pick landing on a line already picked, or on a
deleted line, goes to ``dropped``); OCR predictions and crops move, or are dropped for a
changed line; a page-level corrector's (``corr-*``) whole page is dropped if any of its
lines changed, since the corrector read the page as a whole.

The test set's predictions and crops live in ``data/ocr_predictions/*.json`` and
``runs/ocr_eval/crops/``; another set's in ``data/ocr_predictions/<set>/`` and
``runs/ocr_eval/<set>_crops/`` (as ``dev/ocr_eval/common.use_set`` lays them out).

Every step is idempotent (a stale record already set aside isn't added again), so
``repair`` can be re-run until it reports nothing.

    uv run python -m dev.line_review.migrate backfill   # fingerprint existing records
    uv run python -m dev.line_review.migrate repair     # after the layout review: move everything
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timezone

from . import lines as lines_mod
from . import storage
from . import transcribe as tr

PREDICTIONS_DIR = storage.REPO_ROOT / "data" / "ocr_predictions"
CROPS_DIR = storage.REPO_ROOT / "runs" / "ocr_eval"
_lock = threading.Lock()


def _set_dirs(task: str):
    """(predictions dir, crops dir) of a line set, as dev/ocr_eval/common.use_set has them."""
    if task == tr.TESTSET:
        return PREDICTIONS_DIR, CROPS_DIR / "crops"
    return PREDICTIONS_DIR / task, CROPS_DIR / f"{task}_crops"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tasks() -> list[str]:
    root = tr.TRANSCRIPTIONS_DIR
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []


def _stale_path(page: int, task: str):
    return tr.TRANSCRIPTIONS_DIR / task / "stale" / f"page_{page}.json"


def _write_json(path, obj) -> None:
    storage.write_atomic(path, json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def before_shapes(page: int, previous_verified: dict | None = None) -> dict[str, str]:
    """Old key -> ``geometry`` of the lines whose earlier shape is known: the baseline's
    (``p<N>~line_…``) and, if given, a previous verified output's ids. Keys only the ops
    made have no entry: ``after_verify`` maps them with an unknown shape."""
    from . import materialize as mz
    shapes = {f"p{page}~{l['key']}": tr.geometry(l)
              for l in mz.baseline_lines(storage.load_baseline(page))}
    for l in (previous_verified or {}).get("lines", []):
        shapes[l["id"]] = tr.geometry(l)
    return shapes


def page_map(page: int, page_lines: list[dict], ids: dict[str, str],
             before: dict[str, str | None], retired: dict | None = None) -> tuple[dict, dict, dict]:
    """How each old key on the page maps to the verified lines.

    Returns (``target``, ``changed``, ``now``): old key -> new id (for a split or merged
    line, the first line made from it; None if deleted); old keys whose line changed
    shape, has an unknown earlier shape (``before`` value None), or is gone, with the
    reason; new id -> geometry of the verified line.
    ``retired``: the review's retired ids (``superseded_by``), for old verified ids."""
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
            if shape is None:
                changed[old] = "shape before the review unknown (line made by the review)"
            elif tr.geometry(line) != shape:
                changed[old] = "shape changed"
            continue
        if key:
            successors = [ids[l["key"]] for l in page_lines if key in l.get("lineage", [])]
        else:  # a verified id that was retired: follow superseded_by, in reading order
            order = {ids[l["key"]]: n for n, l in enumerate(page_lines)}
            successors = sorted((i for i in (retired or {}).get(old, {}).get("superseded_by", [])
                                 if i in order), key=order.get)
        target[old] = successors[0] if successors else None
        changed[old] = "line split or merged" if successors else "line removed"
    return target, changed, now


def after_verify(page: int, page_lines: list[dict], ids: dict[str, str],
                 before: dict[str, str] | None = None, retired: dict | None = None) -> dict:
    """Re-key every task's transcriptions, sample picks, predictions and crops on ``page``
    to its verified ids. ``before``: see ``before_shapes`` (computed if None);
    ``retired``: the review's retired ids after minting."""
    if before is None:
        before = before_shapes(page)
    # Map every key the page's data uses, not only those with a known earlier shape: a key
    # the ops made, or one they removed again, would otherwise be skipped and left behind.
    # A live verified id with no earlier shape is taken as unchanged (its records still
    # carry their own geometry).
    live = set(ids.values())
    before = {**{k: None for k in _data_keys(page) if lines_mod.is_baseline_key(k) or k not in live},
              **before}
    target, changed, now = page_map(page, page_lines, ids, before, retired)
    summary = {}
    with _lock:
        for task in _tasks():
            moved, stale = _move_records(page, task, target, changed, now)
            picks = _move_picks(task, target, changed)
            preds = _move_predictions(task, page, target, changed)
            if moved or stale or picks or preds:
                summary[task] = {"moved": moved, "stale": stale, "picks": picks, "predictions": preds}
    return summary


def _on_page(page: int, key: str) -> bool:
    return key.startswith((f"p{page}~", f"p{page}."))


def _data_keys(page: int) -> set[str]:
    """Every key on ``page`` that some task's records, picks, predictions or crops use."""
    keys: set[str] = set()
    for task in _tasks():
        keys |= {k for k in tr.load_page(page, task) if _on_page(page, k)}
        if tr.sample_path(task).exists():
            keys |= {p["id"] for p in tr.load_sample(task)["picks"] if _on_page(page, p["id"])}
        pred_dir, crops = _set_dirs(task)
        for path in sorted(pred_dir.glob("*.json")) if pred_dir.is_dir() else []:
            keys |= {k for k in json.loads(path.read_text(encoding="utf-8")).get("lines", {})
                     if _on_page(page, k)}
        if crops.is_dir():
            keys |= {p.stem for p in crops.glob(f"p{page}[~.]*.png")}
    return keys


def _move_records(page: int, task: str, target: dict, changed: dict, now: dict) -> tuple[int, dict]:
    """A record moves to its line's new id if the line still has the shape it was typed
    against (its ``geometry``; without one, the shape before verify); else it goes stale."""
    records = tr.load_page(page, task)
    moved, stale, set_aside = 0, {}, []
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
        set_aside.append({"id": rid, "reason": why, "replaced_by": new, "at": _now(),
                          "record": records.pop(rid)})
    if set_aside:
        # One write per page, before the page itself. If the page write then fails, a retry
        # finds these records again: skip the ones already set aside (same id, same typing).
        path = _stale_path(page, task)
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        seen = {(s["id"], s["record"].get("at")) for s in old}
        new_entries = [s for s in set_aside if (s["id"], s["record"].get("at")) not in seen]
        if new_entries:
            _write_json(path, old + new_entries)
    if moved or stale:
        tr._write_page(page, task, records)
    return moved, stale


def _move_picks(task: str, target: dict, changed: dict) -> int:
    if not tr.sample_path(task).exists():
        return 0
    sample = tr.load_sample(task)
    picks, dropped, n = [], sample.get("dropped", []), 0
    taken = {p["id"] for p in sample["picks"] if target.get(p["id"], p["id"]) == p["id"]}
    for p in sample["picks"]:
        new = target.get(p["id"], p["id"])
        if new is None:
            dropped.append({**p, "reason": changed[p["id"]], "at": _now()})
            n += 1
            continue
        if new != p["id"] and new in taken:  # merged into (or split onto) a picked line
            dropped.append({**p, "reason": f"{changed.get(p['id'], 'moved')}, onto {new}, "
                                           "already picked", "at": _now()})
            n += 1
            continue
        taken.add(new)
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
    pred_dir, crops = _set_dirs(task)
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
    if crops.is_dir():
        for old, new in target.items():
            src = crops / f"{old}.png"
            if not src.exists():
                continue
            if old in changed or new is None:
                src.unlink()
            elif new != old:
                dst = crops / f"{new}.png"
                if dst.exists():
                    src.unlink()  # same shape, already exported under the new id
                else:
                    src.rename(dst)
    return n


def repair() -> None:
    """Move every verified page's data from its old keys to its line ids. Run once after
    the whole layout review (before any new transcription or OCR); idempotent, so run it
    again after a failure, until it prints nothing."""
    for page in storage.list_pages():
        review = storage.load_review(page)
        if review["status"] != "verified":
            continue
        lines = storage.materialized(page, review)
        summary = after_verify(page, lines, review["ids"], before_shapes(page),
                               retired=review.get("retired"))
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
