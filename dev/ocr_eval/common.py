"""Shared plumbing for the OCR engine runners. Stdlib only: every engine venv imports it.

    runs/ocr_eval/crops/<line id>.png      written by export_crops.py (repo venv)
    data/ocr_predictions/<engine>.json     written by each run_*.py, read by score.py

Pass ``--set ceiling`` to any runner to work on the ceiling set instead
(``runs/ocr_eval/ceiling_crops/`` -> ``data/ocr_predictions/ceiling/``; see ceiling.py).
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
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
    try:
        with lock(PREDICTIONS_DIR / f"{engine}.json"):
            _run(engine, settings, recognize, only_missing, workers)
    except Busy as e:
        sys.exit(str(e))


def _run(engine: str, settings: dict, recognize, only_missing: bool, workers: int) -> None:
    old = load_predictions(engine)
    keep = old.get("lines", {}) if only_missing and old.get("settings") == settings else {}
    # kept lines come from a run with these same settings; whether *all* of the file's
    # lines did is only known if the old file said so
    uniform = not keep or bool(old.get("uniform_settings"))
    lines = dict(keep)
    todo = [p for p in crop_paths() if p.stem not in keep]
    print(f"{engine}: {len(todo)} to predict, {len(keep)} kept")
    start = time.time()
    done = 0

    def handle(png: Path, fut) -> None:
        nonlocal done
        done += 1
        try:
            lines[png.stem] = fut.result()
        except Exception as e:  # one bad line shouldn't lose the run
            print(f"  {png.stem}: {type(e).__name__}: {e}", flush=True)
        if done % 10 == 0 or done == len(todo):
            print(f"  {done}/{len(todo)} ({(time.time() - start) / done:.1f} s/line)", flush=True)
            _write(engine, settings, lines, uniform=uniform)

    interrupted = True  # until drain returns: a second Ctrl-C still saves what was collected
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            interrupted = drain(pool, recognize, todo, handle)
    finally:
        _write(engine, settings, lines, uniform=uniform)
    if interrupted:
        sys.exit(130)


def drain(pool, fn, items, handle) -> bool:
    """Submit ``fn(item)`` to ``pool`` for each of ``items`` and call ``handle(item,
    future)`` as each completes; True if interrupted.

    On Ctrl-C (even while submitting) the calls not started yet are cancelled, so they are
    never sent (a paid API bills every call), and the ones already in flight are still
    collected, so what they cost isn't thrown away. The caller saves, then exits."""
    items = list(items)
    futures, handled = {}, set()
    try:
        for item in items:
            futures[pool.submit(fn, item)] = item
        for fut in as_completed(futures):
            handle(futures[fut], fut)
            handled.add(fut)
        return False
    except KeyboardInterrupt:
        rest = [f for f in futures if f not in handled]
        cancelled = sum(f.cancel() for f in rest) + len(items) - len(futures)  # + never submitted
        in_flight = [f for f in rest if not f.cancelled()]
        print(f"\ninterrupted: {cancelled} not sent; collecting the {len(in_flight)} in flight "
              "(Ctrl-C again to abandon them)", flush=True)
        try:
            for fut in as_completed(in_flight):
                handle(futures[fut], fut)
                handled.add(fut)
        except KeyboardInterrupt:
            lost = sum(f not in handled for f in in_flight)
            print(f"\nWARNING: abandoned {lost} calls in flight: they were sent (and are billed), "
                  "but their results are not saved. Exiting once they return.", flush=True)
            raise
        return True


class Busy(RuntimeError):
    """Another process is working on this predictions file."""


_held: dict[Path, list] = {}  # path -> [fd, depth]


def _acquire(path: Path) -> Path:
    path = Path(path).resolve()
    if path in _held:
        _held[path][1] += 1
        return path
    lock_path = path.with_name(f".{path.name}.lock")  # not a *.json: git ignores it
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = os.pread(fd, 300, 0).decode("utf-8", "replace").strip()
        os.close(fd)
        raise Busy(f"{path.name} is in use by {holder or 'another process'}: "
                   "wait for it to finish (or stop it) and run this again") from None
    os.ftruncate(fd, 0)
    os.pwrite(fd, (f"pid {os.getpid()} since "
                   f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
                   f"({' '.join(sys.argv)[:200]})").encode("utf-8"), 0)
    _held[path] = [fd, 1]
    return path


def _release(path: Path) -> None:
    held = _held[path]
    held[1] -= 1
    if not held[1]:
        del _held[path]
        os.ftruncate(held[0], 0)
        fcntl.flock(held[0], fcntl.LOCK_UN)
        os.close(held[0])


@contextmanager
def lock(path: Path):
    """Hold the predictions file ``path`` for one writer while a run (or migrate) works on
    it: a second shell on the same file stops with ``Busy`` instead of saving over the
    first one's work. Re-entrant within a process. The OS frees it when the process ends,
    however it ends (``kill -9`` too), so no stale lock is ever left behind."""
    held = _acquire(path)
    try:
        yield
    finally:
        _release(held)


def hold(path: Path) -> None:
    """``lock`` for the rest of the process (a command-line tool's whole run)."""
    _acquire(path)


def _write(engine: str, settings: dict, lines: dict, *, uniform: bool = False) -> None:
    """Save a predictions file. ``uniform``: every one of ``lines`` was predicted with
    ``settings`` (the caller knows; the default, False, claims nothing). Only then do the
    readings later set aside from this file say which settings made them."""
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"engine": engine, "settings": settings}
    if uniform:
        rec["uniform_settings"] = True
    rec["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec["lines"] = dict(sorted(lines.items()))
    # Atomic (temp file + rename): a run killed mid-write must not leave a truncated file,
    # which every later reader (score, migrate) would fail on.
    path = PREDICTIONS_DIR / f"{engine}.json"
    with lock(path):
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


def stale_entry(old: dict, text: str, reason: str, replaced_by, at: str, known: dict) -> dict:
    """A ``stale`` entry for ``text``, a line of the predictions file ``old`` (also used by
    dev/line_review/migrate.py). ``predicted_before``: the file's last save before the
    line was set aside (the reading is at least that old). ``settings``: an id into
    ``stale_settings`` (``known`` gets it), only if the file says all its lines were made
    with its settings (``uniform_settings``); otherwise left out, not guessed."""
    entry = {"text": text, "reason": reason, "replaced_by": replaced_by, "at": at}
    if old.get("generated_at"):
        entry["predicted_before"] = old["generated_at"]
    if old.get("uniform_settings"):
        sid = settings_id(old.get("settings"))
        entry["settings"] = sid
        known[sid] = old.get("settings")
    return entry


def current_crop(entries: list[dict]) -> int:
    """Index of a line's first ``stale`` entry for its current crop: the one after its
    last migrate set-aside (any reason but a rewrite), or 0 if it has none."""
    return max((i + 1 for i, e in enumerate(entries) if e["reason"] not in REWRITE_REASONS),
               default=0)


def set_aside(old: dict, lines: dict) -> tuple[dict, dict]:
    """The ``stale`` and ``stale_settings`` sections for a rewrite of ``old`` (a
    predictions file) with ``lines``.

    No reading is ever deleted: these files hold paid, nondeterministic runs that the
    committed scores were measured on. A rewrite keeps the old ``stale`` section (lines
    the layout review changed, set aside by dev/line_review/migrate.py, kept as they are)
    and adds every old line the new ``lines`` drop, or replace with a materially different
    text (``reading``), in the same ``{key: [{text, reason, replaced_by, at}]}`` form.
    Entries also carry ``predicted_before`` and, when known, ``settings`` (``stale_entry``).

    A run saves as it goes, so a line it hasn't reached yet is first set aside as
    dropped; once the run writes it, the entry becomes "replaced on rewrite", or goes
    if the new text is the same reading (nothing is lost: it is the line).

    That applies only to readings of the line's current crop. Entries up to the line's
    last migrate set-aside (``shape changed`` and the like) read an older crop, so a new
    reading that matches one is a different prediction, and both are kept."""
    stale = {k: [dict(e) for e in v] for k, v in old.get("stale", {}).items()}
    known = dict(old.get("stale_settings", {}))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for key, text in old.get("lines", {}).items():
        if key in lines and (lines[key] == text or reading(lines[key]) == reading(text)):
            continue
        entries = stale.get(key, [])
        if any(reading(e["text"]) == reading(text) for e in entries[current_crop(entries):]):
            continue
        dropped = key not in lines
        stale.setdefault(key, []).append(stale_entry(
            old, text, REWRITE_REASONS[0] if dropped else REWRITE_REASONS[1],
            None if dropped else key, now, known))
    for key in list(stale):
        cut = current_crop(stale[key])
        kept = stale[key][:cut]  # older crops' readings: never cancelled by a new one
        for e in stale[key][cut:]:
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
