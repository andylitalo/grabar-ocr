"""
One-time migration to the method-tag artifact convention (see data/README.md).

Renames every per-page derived artifact so the *method that produced it* rides on
the page id: page_XXXX -> page_XXXX_human | page_XXXX_auto. This lets a human and
an automated (data_prep.auto_slice) run of the same page coexist instead of
overwriting each other at the same paths.

Scope (where human/auto actually collide):
  - data/lines/page_XXXX/                      -> data/lines/page_XXXX_M/
  - data/columns/page_XXXX_column_Y.png        -> data/columns/page_XXXX_M_column_Y.png
  - data/columns/boxes/page_XXXX.json          -> data/columns/boxes/page_XXXX_M.json
  - data/predictions/<tag>/page_XXXX/          -> data/predictions/<tag>/page_XXXX_M/
  - reports/*.{html,csv,json,md}               -> page_XXXX tokens repointed to page_XXXX_M

Intentionally LEFT ALONE (already-unambiguous human/derived sets, or tied to the
frozen training-id system):
  - data/golden/, data/frozen_test_set/ (incl. manifest line-ids),
    data/phase4_dataset/ (freeze marker), data/phase4_scaling/, and the
    data/predictions/<tag>/frozen_test_set/ prediction dirs.

Classification: a page is "human" iff its number is in HUMAN_PAGES (it has hand
transcriptions in data/lines); every other page (486, 487, the 0100-0140 detector
sample, ...) is "auto".

Idempotent: artifacts already ending in _human/_auto are skipped. Every move is
recorded to data/backups/method_tag_migration_<ts>.json so it can be reversed.

Usage:
    python -m data_prep.migrate_method_tags            # dry run (prints the plan)
    python -m data_prep.migrate_method_tags --execute  # perform the moves
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
BOXES = COLUMNS / "boxes"
PREDICTIONS = DATA / "predictions"
REPORTS = REPO / "reports"
BACKUPS = DATA / "backups"

# Pages with hand transcriptions in data/lines (the human-labeled set). Everything
# else is auto. Kept explicit so reclassification is a one-line, auditable change.
HUMAN_PAGES = {51, 200, 251, 300, 400, 451, 499, 543, 550, 559}

# Prediction subdirs that are not per-page pages and must not be suffixed.
NON_PAGE_PRED_DIRS = {"frozen_test_set"}

_PAGE_DIR_RE = re.compile(r"^page_(\d{4})$")
_COL_PNG_RE = re.compile(r"^page_(\d{4})_column_(\d+)\.png$")
_BOX_JSON_RE = re.compile(r"^page_(\d{4})\.json$")
# A bare 4-digit page id not already method-suffixed and not part of a longer number.
_PAGE_TOKEN_RE = re.compile(r"page_(\d{4})(?![_\d])")


def method_for(n: int) -> str:
    return "human" if n in HUMAN_PAGES else "auto"


def plan_moves() -> list[tuple[Path, Path]]:
    """Build the (src, dst) rename list for line/column/box/prediction artifacts."""
    moves: list[tuple[Path, Path]] = []

    # 1) line page dirs
    if LINES.is_dir():
        for d in sorted(LINES.iterdir()):
            m = _PAGE_DIR_RE.match(d.name)
            if d.is_dir() and m:
                n = int(m.group(1))
                moves.append((d, LINES / f"page_{n:04d}_{method_for(n)}"))

    # 2) column crops
    if COLUMNS.is_dir():
        for f in sorted(COLUMNS.glob("*.png")):
            m = _COL_PNG_RE.match(f.name)
            if m:
                n, col = int(m.group(1)), m.group(2)
                moves.append((f, COLUMNS / f"page_{n:04d}_{method_for(n)}_column_{col}.png"))

    # 3) column boxes
    if BOXES.is_dir():
        for f in sorted(BOXES.glob("*.json")):
            m = _BOX_JSON_RE.match(f.name)
            if m:
                n = int(m.group(1))
                moves.append((f, BOXES / f"page_{n:04d}_{method_for(n)}.json"))

    # 4) predictions: one page-dir layer under each model tag
    if PREDICTIONS.is_dir():
        for tag_dir in sorted(PREDICTIONS.iterdir()):
            if not tag_dir.is_dir():
                continue
            for d in sorted(tag_dir.iterdir()):
                if d.name in NON_PAGE_PRED_DIRS:
                    continue
                m = _PAGE_DIR_RE.match(d.name)
                if d.is_dir() and m:
                    n = int(m.group(1))
                    moves.append((d, tag_dir / f"page_{n:04d}_{method_for(n)}"))

    return moves


def plan_report_repoints() -> list[tuple[Path, int]]:
    """Reports whose content has bare page tokens to repoint. Returns (path, n_subs)."""
    out: list[tuple[Path, int]] = []
    if not REPORTS.is_dir():
        return out
    for f in sorted(REPORTS.glob("*")):
        if f.suffix.lower() not in {".html", ".csv", ".json", ".md"}:
            continue
        text = f.read_text(encoding="utf-8")
        n_subs = len(_PAGE_TOKEN_RE.findall(text))
        if n_subs:
            out.append((f, n_subs))
    return out


def _repoint_text(text: str) -> str:
    def sub(m: re.Match) -> str:
        n = int(m.group(1))
        return f"page_{n:04d}_{method_for(n)}"

    return _PAGE_TOKEN_RE.sub(sub, text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="perform the moves (default: dry run)")
    args = ap.parse_args()

    moves = plan_moves()
    reports = plan_report_repoints()

    print(f"== Method-tag migration {'(EXECUTE)' if args.execute else '(DRY RUN)'} ==\n")
    print(f"Artifact renames: {len(moves)}")
    for src, dst in moves:
        flag = ""
        if dst.exists():
            flag = "  !! TARGET EXISTS — SKIP"
        print(f"  {src.relative_to(REPO)}  ->  {dst.name}{flag}")
    print(f"\nReport repoints: {len(reports)} file(s)")
    for f, n in reports:
        print(f"  {f.relative_to(REPO)}  ({n} token(s))")

    if not args.execute:
        print("\nDry run only. Re-run with --execute to apply.")
        return

    log: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "moves": [],
        "reports": [],
    }
    for src, dst in moves:
        if dst.exists():
            print(f"SKIP (exists): {dst}")
            continue
        shutil.move(str(src), str(dst))
        log["moves"].append({"src": str(src.relative_to(REPO)), "dst": str(dst.relative_to(REPO))})
    for f, _ in reports:
        new = _repoint_text(f.read_text(encoding="utf-8"))
        f.write_text(new, encoding="utf-8")
        log["reports"].append(str(f.relative_to(REPO)))

    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = BACKUPS / f"method_tag_migration_{stamp}.json"
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"\nDone: {len(log['moves'])} moved, {len(log['reports'])} reports repointed.")
    print(f"Reversal log: {log_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
