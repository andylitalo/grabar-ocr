"""Shared plumbing for the OCR engine runners. Stdlib only: every engine venv imports it.

    runs/ocr_eval/crops/<line id>.png      written by export_crops.py (repo venv)
    data/ocr_predictions/<engine>.json     written by each run_*.py, read by score.py

Pass ``--set ceiling`` to any runner to work on the ceiling set instead
(``runs/ocr_eval/ceiling_crops/`` -> ``data/ocr_predictions/ceiling/``; see ceiling.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CROPS_DIR = REPO_ROOT / "runs" / "ocr_eval" / "crops"
PREDICTIONS_DIR = REPO_ROOT / "data" / "ocr_predictions"


def use_set(name: str) -> None:
    """Point the runners at another line set ("testset" is the default)."""
    global CROPS_DIR, PREDICTIONS_DIR
    if name != "testset":
        CROPS_DIR = REPO_ROOT / "runs" / "ocr_eval" / f"{name}_crops"
        PREDICTIONS_DIR = REPO_ROOT / "data" / "ocr_predictions" / name


def crop_paths(ids: list[str] | None = None) -> list[Path]:
    """Exported crops, optionally limited to ``ids``, in id order."""
    paths = sorted(CROPS_DIR.glob("p*.png"))  # p457.023 (verified) or p520~line_013 (baseline)
    if not paths:
        sys.exit(f"No crops in {CROPS_DIR}: run `uv run python -m dev.ocr_eval.export_crops` first")
    return [p for p in paths if ids is None or p.stem in ids]


def load_predictions(engine: str) -> dict:
    path = PREDICTIONS_DIR / f"{engine}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def run(engine: str, settings: dict, recognize, *, only_missing: bool = True,
        workers: int = 1) -> None:
    """Call ``recognize(png_path) -> str`` on every crop and write the predictions file.

    With ``only_missing`` (default), lines already predicted with the same settings are
    kept, so new picks can be added without re-running the whole set. ``workers`` > 1
    runs lines concurrently (for API engines, where each call mostly waits).
    """
    old = load_predictions(engine)
    keep = old.get("lines", {}) if only_missing and old.get("settings") == settings else {}
    lines = dict(keep)
    todo = [p for p in crop_paths() if p.stem not in keep]
    print(f"{engine}: {len(todo)} to predict, {len(keep)} kept")
    start = time.time()
    done = 0

    def handle(fut) -> None:
        nonlocal done
        done += 1
        png = futures[fut]
        try:
            lines[png.stem] = fut.result()
        except Exception as e:  # one bad line shouldn't lose the run
            print(f"  {png.stem}: {type(e).__name__}: {e}", flush=True)
        if done % 10 == 0 or done == len(todo):
            print(f"  {done}/{len(todo)} ({(time.time() - start) / done:.1f} s/line)", flush=True)
            _write(engine, settings, lines)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(recognize, png): png for png in todo}
        interrupted = drain(futures, handle)
    _write(engine, settings, lines)
    if interrupted:
        sys.exit(130)


def drain(futures, handle) -> bool:
    """Call ``handle(future)`` on each of ``futures`` as it completes; True if interrupted.

    On Ctrl-C the calls not started yet are cancelled, so they are never sent (a paid API
    bills every call), and the ones already in flight are still collected, so what they
    cost isn't thrown away. The caller saves, then exits."""
    handled = set()
    try:
        for fut in as_completed(futures):
            handle(fut)
            handled.add(fut)
        return False
    except KeyboardInterrupt:
        rest = [f for f in futures if f not in handled]
        cancelled = sum(f.cancel() for f in rest)
        in_flight = [f for f in rest if not f.cancelled()]
        print(f"\ninterrupted: {cancelled} not sent; collecting the {len(in_flight)} in flight",
              flush=True)
        for fut in as_completed(in_flight):
            handle(fut)
        return True


def _write(engine: str, settings: dict, lines: dict) -> None:
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"engine": engine, "settings": settings,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "lines": dict(sorted(lines.items()))}
    # Atomic (temp file + rename): a run killed mid-write must not leave a truncated file,
    # which every later reader (score, migrate) would fail on.
    path = PREDICTIONS_DIR / f"{engine}.json"
    stale, stale_settings = set_aside(load_predictions(engine), rec["lines"])
    if stale:
        rec["stale"] = stale
    if stale_settings:
        rec["stale_settings"] = stale_settings
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


REWRITE_REASONS = ("dropped on rewrite", "replaced on rewrite")


def reading(text: str) -> str:
    """A prediction as the strictest score compares it (``score.normalize(fold=False)``,
    the test set's raw column: NFC, whitespace collapsed). Two texts equal here score the
    same everywhere, so a rewrite that changes only this much isn't a new reading."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def settings_id(settings) -> str:
    return hashlib.sha256(json.dumps(settings, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()[:12]


def set_aside(old: dict, lines: dict) -> tuple[dict, dict]:
    """The ``stale`` and ``stale_settings`` sections for a rewrite of ``old`` (a
    predictions file) with ``lines``.

    No reading is ever deleted: these files hold paid, nondeterministic runs that the
    committed scores were measured on. A rewrite keeps the old ``stale`` section (lines
    the layout review changed, set aside by dev/line_review/migrate.py, kept as they are)
    and adds every old line the new ``lines`` drop, or replace with a materially different
    text (``reading``), in the same ``{key: [{text, reason, replaced_by, at}]}`` form.
    Rewrite entries also carry ``run`` (the old file's ``generated_at``) and ``settings``
    (an id into ``stale_settings``, which holds the settings the file carried then).

    A run saves as it goes, so a line it hasn't reached yet is first set aside as
    dropped; once the run writes it, the entry becomes "replaced on rewrite", or goes
    if the new text is the same reading (nothing is lost: it is the line)."""
    stale = {k: [dict(e) for e in v] for k, v in old.get("stale", {}).items()}
    known = dict(old.get("stale_settings", {}))
    sid = settings_id(old.get("settings"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for key, text in old.get("lines", {}).items():
        if key in lines and (lines[key] == text or reading(lines[key]) == reading(text)):
            continue
        if any(reading(e["text"]) == reading(text) for e in stale.get(key, [])):
            continue
        dropped = key not in lines
        stale.setdefault(key, []).append({
            "text": text, "reason": REWRITE_REASONS[0] if dropped else REWRITE_REASONS[1],
            "replaced_by": None if dropped else key, "at": now,
            "run": old.get("generated_at"), "settings": sid})
        known[sid] = old.get("settings")
    for key in list(stale):
        kept = []
        for e in stale[key]:
            if e["reason"] in REWRITE_REASONS and key in lines:
                if lines[key] == e["text"] or reading(lines[key]) == reading(e["text"]):
                    continue
                if e["reason"] == REWRITE_REASONS[0]:
                    e = {**e, "reason": REWRITE_REASONS[1], "replaced_by": key}
            kept.append(e)
        if kept:
            stale[key] = kept
        else:
            del stale[key]
    used = {e.get("settings") for v in stale.values() for e in v}
    return dict(sorted(stale.items())), {s: v for s, v in sorted(known.items()) if s in used}


def add_set_arg(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--set", default="testset", help="line set: testset (default) or ceiling")


def args(description: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--redo", action="store_true", help="re-predict every line")
    add_set_arg(ap)
    a = ap.parse_args()
    use_set(a.set)
    return a
