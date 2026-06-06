"""
verify_slicing.py
Phase 4.5 regression gate for line slicing.

The bug: the old slicer merged two text lines into one crop when the trough
between them stayed above the 2% threshold (tight leading, or ascenders/
descenders bridging the gap). The fix adds an over-segmentation guard that splits
an oversized run at its deepest interior trough.

How this verifies it (honest, no ground-truth needed):
  * Re-slice every column PNG with BOTH the old fixed-threshold algorithm and the
    new guarded one. This is apples-to-apples (the committed data/lines counts are
    not — they are human-curated with rejected/edited crops).
  * GATE 1 (no regressions): new boundary count >= old for every column. The fix
    must only *split* merged runs, never fuse or drop lines.
  * GATE 2 (real gaps): every introduced split cut sits in a genuine low-density
    trough (below TROUGH_DEPTH_FRACTION of its flanking peaks). This is what keeps
    decorative drop-caps and ornament bands -- legitimately *tall single* crops --
    from being over-split; a height threshold alone false-positives on them.
  * Renders each split region (with the cut drawn) to data/_split_debug/ for a
    visual spot-check.

Read-only w.r.t. the dataset: writes only to scratch dirs under data/, never over
data/lines/, data/phase4_dataset/, or the freeze (see data_prep/freeze_phase4.py).

Run (base env):
    uv run python data_prep/verify_slicing.py
Exit code is non-zero if any gate fails.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # package = false -> make data_prep importable

from data_prep.line_cropper import (  # noqa: E402
    MIN_LINE_HEIGHT,
    THRESHOLD_FRACTION,
    TROUGH_DEPTH_FRACTION,
    _smooth,
    crop_lines,
    find_line_boundaries,
    horizontal_projection,
)

logger = logging.getLogger(__name__)

COLUMNS_DIR = REPO / "data/columns"
SCRATCH_DIR = REPO / "data/_slicing_check"
DEBUG_DIR = REPO / "data/_split_debug"


def _old_boundaries(
    projection: np.ndarray,
    min_line_height: int = MIN_LINE_HEIGHT,
    threshold_fraction: float = THRESHOLD_FRACTION,
) -> list[tuple[int, int]]:
    """The pre-fix slicer: fixed-threshold runs, no over-segmentation guard."""
    threshold = threshold_fraction * float(projection.max())
    is_text = projection > threshold
    bounds: list[tuple[int, int]] = []
    in_line = False
    start = 0
    for i, t in enumerate(is_text):
        if t and not in_line:
            start, in_line = i, True
        elif not t and in_line:
            if i - start >= min_line_height:
                bounds.append((start, i))
            in_line = False
    if in_line:
        bounds.append((start, len(is_text)))
    return bounds


def _trough_ratio(smoothed: np.ndarray, top: int, cut: int, bottom: int) -> float:
    """smoothed[cut] / min(flanking peak) — how deep the split valley is."""
    left = float(smoothed[top:cut].max()) if cut > top else float(smoothed[cut])
    right = float(smoothed[cut:bottom].max()) if cut < bottom else float(smoothed[cut])
    flank = min(left, right)
    return float(smoothed[cut]) / flank if flank > 0 else 1.0


def verify() -> int:
    for d in (SCRATCH_DIR, DEBUG_DIR):
        if d.exists():
            shutil.rmtree(d)

    column_pngs = sorted(COLUMNS_DIR.glob("*.png"))
    if not column_pngs:
        logger.error("No column PNGs under %s", COLUMNS_DIR)
        return 2

    rows: list[tuple[str, int, int, int]] = []  # (col_name, old_n, new_n, n_splits)
    regressions: list[str] = []
    shallow_cuts: list[str] = []  # cuts that are NOT in a real trough (should be none)
    tot_old = tot_new = tot_splits = 0

    for png in column_pngs:
        image = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
        if image is None:
            logger.warning("Cannot read %s", png)
            continue
        proj = horizontal_projection(image)
        smoothed = _smooth(proj.astype(np.float32), 7)

        old = _old_boundaries(proj)
        new = find_line_boundaries(proj)
        tot_old += len(old)
        tot_new += len(new)

        if len(new) < len(old):
            regressions.append(f"{png.stem}: old={len(old)} -> new={len(new)}")

        # Materialize new crops into scratch (for downstream eyeballing).
        crop_lines(png, SCRATCH_DIR / png.stem)

        # Identify which old runs the guard split, and sanity-check each cut.
        n_splits = 0
        for ot, ob in old:
            pieces = [(t, b) for t, b in new if t >= ot and b <= ob + 1]
            if len(pieces) <= 1:
                continue
            n_splits += len(pieces) - 1
            for t, _ in pieces[1:]:
                if _trough_ratio(smoothed, ot, t, ob) >= TROUGH_DEPTH_FRACTION:
                    shallow_cuts.append(f"{png.stem} cut@{t} in run {ot}-{ob}")
            _render_split(image, ot, ob, pieces, DEBUG_DIR / png.stem, n_splits)

        tot_splits += n_splits
        rows.append((png.stem, len(old), len(new), n_splits))

    _report(rows, tot_old, tot_new, tot_splits)

    print("\n" + "=" * 56)
    ok = True
    if regressions:
        ok = False
        print(f"GATE 1 FAIL: {len(regressions)} column(s) LOST lines (over-merge):")
        for r in regressions:
            print(f"   {r}")
    else:
        print("GATE 1 PASS: no column lost lines (new >= old everywhere).")
    if shallow_cuts:
        ok = False
        print(f"GATE 2 FAIL: {len(shallow_cuts)} split cut(s) not in a real trough:")
        for c in shallow_cuts:
            print(f"   {c}")
    else:
        print("GATE 2 PASS: every introduced cut sits in a genuine inter-line trough.")
    print(f"\nIntroduced {tot_splits} split(s). Eyeball: {DEBUG_DIR}")
    return 0 if ok else 1


def _render_split(image, top, bottom, pieces, out_dir: Path, idx: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pad = 2
    region = cv2.cvtColor(image[max(0, top - pad) : bottom + pad, :], cv2.COLOR_GRAY2BGR)
    for t, _ in pieces[1:]:
        y = t - max(0, top - pad)
        cv2.line(region, (0, y), (region.shape[1], y), (0, 0, 255), 2)
    cv2.imwrite(str(out_dir / f"split_{idx:02d}_rows{top}-{bottom}.png"), region)


def _report(rows, tot_old, tot_new, tot_splits) -> None:
    print(f"\nRe-sliced {len(rows)} columns (old algo vs new guarded algo)\n")
    print(f"{'column':<24}{'old':>6}{'new':>6}{'splits':>8}")
    print("-" * 44)
    for name, old_n, new_n, n_splits in rows:
        mark = f"  +{n_splits}" if n_splits else ""
        print(f"{name:<24}{old_n:>6}{new_n:>6}{n_splits:>8}{mark}")
    print("-" * 44)
    print(f"{'TOTAL':<24}{tot_old:>6}{tot_new:>6}{tot_splits:>8}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    argparse.ArgumentParser(
        description="Re-slice labeled pages (old vs new) and gate on no regressions "
        "+ real-trough splits."
    ).parse_args()
    sys.exit(verify())


if __name__ == "__main__":
    main()
