"""
One-time migration to the region artifact convention (see data/README.md, Phase 6).

Renames the legacy two-column artifacts so each line-crop dir / column PNG carries
its reading order and type: column_N -> region_NN_<type>. A plain two-column page
becomes region_01_left / region_02_right. This replaces the implicit
``sorted(glob("column_*"))`` ordering with an explicit, typed, ordered region model
that also accommodates single-column bands and headers (region_NN_single/header).

Mapping:
  column_1 -> region_01_left, column_2 -> region_02_right,
  column_N (N>=3) -> region_NN_single   (no two-column page exceeds 2 today)

Scope (every place a ``column_N`` token addresses a region):
  - data/lines/page_XXXX_M/column_N/                 -> region_NN_<type>/
  - data/columns/page_XXXX_M_column_N.png            -> page_XXXX_M_region_NN_<type>.png
  - data/predictions/<tag>/page_XXXX_M/column_N/     -> region_NN_<type>/
  - data/predictions/<tag>/page_XXXX_M/predictions.json   "lines" keys repointed
  - data/lines/page_XXXX_M/nonchar_truth.json             "lines" keys repointed

Intentionally LEFT ALONE (flat, no column subdirs): data/golden/,
data/frozen_test_set/, data/phase4_dataset/, data/phase4_scaling/.

Idempotent: only ``column_N`` names/keys are matched, so artifacts already named
``region_*`` are skipped. Every move + JSON repoint is recorded to
data/backups/region_rename_<ts>.json so it can be reversed.

Usage:
    python -m data_prep.migrate_region_names            # dry run (prints the plan)
    python -m data_prep.migrate_region_names --execute  # perform the migration
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
LINES = DATA / "lines"
COLUMNS = DATA / "columns"
PREDICTIONS = DATA / "predictions"
BACKUPS = DATA / "backups"

_COL_DIR_RE = re.compile(r"^column_(\d+)$")
_COL_PNG_RE = re.compile(r"^(.+)_column_(\d+)\.png$")
# A column line-id key at the start of a region path: "column_3/line_007".
_COL_KEY_RE = re.compile(r"^column_(\d+)/")

# Prediction subdirs that are not per-page pages (kept flat, never column-split).
NON_PAGE_PRED_DIRS = {"frozen_test_set"}


def region_for_col(col: int) -> str:
    """column index -> region dir/key, e.g. 1 -> 'region_01_left', 3 -> 'region_03_single'."""
    rtype = {1: "left", 2: "right"}.get(col, "single")
    return f"region_{col:02d}_{rtype}"


def _repoint_key(key: str) -> str:
    """'column_N/line_NNN' -> '<region>/line_NNN'; pass through anything else."""
    return _COL_KEY_RE.sub(lambda m: region_for_col(int(m.group(1))) + "/", key)


def plan_moves() -> list[tuple[Path, Path]]:
    """(src, dst) renames for line dirs, column PNGs, and prediction line dirs."""
    moves: list[tuple[Path, Path]] = []

    # 1) line page region dirs: data/lines/<page>/column_N
    if LINES.is_dir():
        for page_dir in sorted(LINES.iterdir()):
            if not page_dir.is_dir():
                continue
            for d in sorted(page_dir.iterdir()):
                m = _COL_DIR_RE.match(d.name)
                if d.is_dir() and m:
                    moves.append((d, page_dir / region_for_col(int(m.group(1)))))

    # 2) column crops: data/columns/<page>_column_N.png
    if COLUMNS.is_dir():
        for f in sorted(COLUMNS.glob("*.png")):
            m = _COL_PNG_RE.match(f.name)
            if m:
                stem, col = m.group(1), int(m.group(2))
                moves.append((f, COLUMNS / f"{stem}_{region_for_col(col)}.png"))

    # 3) prediction per-line dirs: data/predictions/<tag>/<page>/column_N
    if PREDICTIONS.is_dir():
        for tag_dir in sorted(PREDICTIONS.iterdir()):
            if not tag_dir.is_dir():
                continue
            for page_dir in sorted(tag_dir.iterdir()):
                if not page_dir.is_dir() or page_dir.name in NON_PAGE_PRED_DIRS:
                    continue
                for d in sorted(page_dir.iterdir()):
                    m = _COL_DIR_RE.match(d.name)
                    if d.is_dir() and m:
                        moves.append((d, page_dir / region_for_col(int(m.group(1)))))

    return moves


def plan_key_repoints() -> list[tuple[Path, int]]:
    """JSON files whose 'lines' keys use column_N/ and need repointing. (path, n_keys)."""
    out: list[tuple[Path, int]] = []
    candidates: list[Path] = []
    if LINES.is_dir():
        candidates += sorted(LINES.glob("page_*/nonchar_truth.json"))
    if PREDICTIONS.is_dir():
        candidates += sorted(PREDICTIONS.glob("*/page_*/predictions.json"))
    for f in candidates:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        lines = data.get("lines")
        if isinstance(lines, dict):
            n = sum(1 for k in lines if _COL_KEY_RE.match(k))
            if n:
                out.append((f, n))
    return out


def _repoint_file(path: Path) -> int:
    """Rewrite a JSON file's 'lines' keys column_N/ -> region/. Returns keys changed."""
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = data.get("lines", {})
    new_lines, changed = {}, 0
    for key, value in lines.items():
        new_key = _repoint_key(key)
        if new_key != key:
            changed += 1
        new_lines[new_key] = value
    data["lines"] = new_lines
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return changed


def apply_migration(
    moves: list[tuple[Path, Path]], repoints: list[tuple[Path, int]]
) -> dict:
    """Perform the renames + JSON key repoints; return the reversal log (also saved).

    Targets that already exist are skipped (idempotent). The log records every
    move and every file repointed so the migration can be reversed.
    """
    log: dict = {"timestamp": datetime.now(timezone.utc).isoformat(), "moves": [], "repoints": []}
    for src, dst in moves:
        if dst.exists():
            print(f"SKIP (exists): {dst}")
            continue
        shutil.move(str(src), str(dst))
        log["moves"].append({"src": str(src.relative_to(REPO)), "dst": str(dst.relative_to(REPO))})
    for f, _ in repoints:
        changed = _repoint_file(f)
        log["repoints"].append({"file": str(f.relative_to(REPO)), "keys": changed})

    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = BACKUPS / f"region_rename_{stamp}.json"
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"\nDone: {len(log['moves'])} moved, {len(log['repoints'])} JSON files repointed.")
    print(f"Reversal log: {log_path.relative_to(REPO)}")
    return log


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--execute", action="store_true", help="perform the migration (default: dry run)")
    args = ap.parse_args()

    moves = plan_moves()
    repoints = plan_key_repoints()

    print(f"== Region-name migration {'(EXECUTE)' if args.execute else '(DRY RUN)'} ==\n")
    print(f"Artifact renames: {len(moves)}")
    for src, dst in moves:
        flag = "  !! TARGET EXISTS — SKIP" if dst.exists() else ""
        print(f"  {src.relative_to(REPO)}  ->  {dst.name}{flag}")
    print(f"\nJSON key repoints: {len(repoints)} file(s)")
    for f, n in repoints:
        print(f"  {f.relative_to(REPO)}  ({n} key(s))")

    if not args.execute:
        print("\nDry run only. Re-run with --execute to apply.")
        return

    apply_migration(moves, repoints)


if __name__ == "__main__":
    main()
