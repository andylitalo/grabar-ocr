"""Shared plumbing for the OCR engine runners. Stdlib only: every engine venv imports it.

    runs/ocr_eval/crops/<line id>.png      written by export_crops.py (repo venv)
    data/ocr_predictions/<engine>.json     written by each run_*.py, read by score.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CROPS_DIR = REPO_ROOT / "runs" / "ocr_eval" / "crops"
PREDICTIONS_DIR = REPO_ROOT / "data" / "ocr_predictions"


def crop_paths(ids: list[str] | None = None) -> list[Path]:
    """Exported crops, optionally limited to ``ids``, in id order."""
    paths = sorted(CROPS_DIR.glob("p*.png"))
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
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(recognize, png): png for png in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            png = futures[fut]
            try:
                lines[png.stem] = fut.result()
            except Exception as e:  # one bad line shouldn't lose the run
                print(f"  {png.stem}: {type(e).__name__}: {e}", flush=True)
            if n % 10 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)} ({(time.time() - start) / n:.1f} s/line)", flush=True)
                _write(engine, settings, lines)
    _write(engine, settings, lines)


def _write(engine: str, settings: dict, lines: dict) -> None:
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"engine": engine, "settings": settings,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "lines": dict(sorted(lines.items()))}
    (PREDICTIONS_DIR / f"{engine}.json").write_text(
        json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def args(description: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--redo", action="store_true", help="re-predict every line")
    return ap.parse_args()
