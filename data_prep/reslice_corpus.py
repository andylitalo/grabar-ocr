"""
reslice_corpus.py
Non-destructive re-slice of every labeled page with the fixed line slicer,
carrying existing labels forward.

For each column PNG in data/columns/ it re-runs the (fixed) find_line_boundaries
and writes corrected single-line crops to data/lines_resliced/<page>/<column>/.
Labels are migrated by matching each new crop to the OLD-algorithm run it overlaps,
whose status (labeled / empty-marker / pending / rejected) is looked up by exact
pixel hash against the committed data/lines crops:

  * unchanged crop  -> overlaps exactly one old run == itself        -> carry .txt
  * split child     -> overlaps a *labeled* old (merged) run         -> NEEDS RELABEL,
                       the old merged label is attached as a hint
  * rejected match  -> overlaps a rejected old crop                  -> written to
                       <column>/rejected/, no label needed
  * pending / unlabeled page -> overlaps a pending old run           -> stays pending

data/lines is never modified. A worklist of crops needing a (re)label is written
to data/lines_resliced/relabel_worklist.json.

Run (base env):
    uv run python data_prep/reslice_corpus.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # package = false -> make data_prep importable

from data_prep.line_cropper import find_line_boundaries, horizontal_projection  # noqa: E402
from data_prep.verify_slicing import _old_boundaries  # noqa: E402

logger = logging.getLogger(__name__)

COLUMNS_DIR = REPO / "data/columns"
LINES_DIR = REPO / "data/lines"
OUT_DIR = REPO / "data/lines_resliced"
WORKLIST = OUT_DIR / "relabel_worklist.json"
PAD = 4  # must match crop_lines() so unchanged crops are byte-identical

_COL_RE = re.compile(r"^(page_\d+)_column_(\d+)\.png$")


def _crop(image: np.ndarray, top: int, bottom: int) -> np.ndarray:
    return image[max(0, top - PAD) : min(image.shape[0], bottom + PAD), :]


def _hash(a: np.ndarray) -> str:
    return hashlib.sha1(repr(a.shape).encode() + a.tobytes()).hexdigest()


def _index_old_labels(col_dir: Path) -> dict[str, tuple[str, str]]:
    """pixel-hash -> (status, text) for every committed crop of a column.

    status in {"labeled", "marker", "pending", "rejected"}; text is the label
    (possibly "") for labeled/marker, else "".
    """
    idx: dict[str, tuple[str, str]] = {}
    if not col_dir.exists():
        return idx
    for png in sorted(col_dir.glob("line_*.png")):
        a = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
        if a is None:
            continue
        txt_p = png.with_suffix(".txt")
        if txt_p.exists():
            text = txt_p.read_text(encoding="utf-8")
            idx.setdefault(_hash(a), ("labeled" if text.strip() else "marker", text))
        else:
            idx.setdefault(_hash(a), ("pending", ""))
    rej = col_dir / "rejected"
    if rej.exists():
        for png in sorted(rej.glob("line_*.png")):
            a = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
            if a is not None:
                idx.setdefault(_hash(a), ("rejected", ""))
    return idx


def _old_runs_with_status(
    image: np.ndarray, proj: np.ndarray, old_index: dict[str, tuple[str, str]]
) -> list[tuple[int, int, str, str]]:
    """Old-algorithm runs as (top, bottom, status, text), status via pixel hash."""
    runs = []
    for ot, ob in _old_boundaries(proj):
        status, text = old_index.get(_hash(_crop(image, ot, ob)), ("pending", ""))
        runs.append((ot, ob, status, text))
    return runs


def _overlap_index(top: int, bottom: int, old_runs) -> int:
    """Index of the old run with the most vertical overlap (-1 if none)."""
    best, best_ov = -1, 0
    for j, (ot, ob, _status, _text) in enumerate(old_runs):
        ov = max(0, min(bottom, ob) - max(top, ot))
        if ov > best_ov:
            best, best_ov = j, ov
    return best


def reslice() -> int:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)

    column_pngs = sorted(COLUMNS_DIR.glob("*.png"))
    if not column_pngs:
        logger.error("No column PNGs under %s", COLUMNS_DIR)
        return 2

    pages: dict[str, dict[str, int]] = {}
    worklist: list[dict] = []

    for png in column_pngs:
        m = _COL_RE.match(png.name)
        if not m:
            continue
        page_id, col = m.group(1), int(m.group(2))
        image = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        proj = horizontal_projection(image)

        old_index = _index_old_labels(LINES_DIR / page_id / f"column_{col}")
        old_runs = _old_runs_with_status(image, proj, old_index)
        new_bounds = find_line_boundaries(proj)

        out_col = OUT_DIR / page_id / f"column_{col}"
        out_col.mkdir(parents=True, exist_ok=True)

        rec = pages.setdefault(
            page_id,
            dict(crops=0, carried=0, autosplit=0, markers=0, pending=0, rejected=0, relabel=0),
        )

        # Group new crops by the old run they fall in (so a split run's children
        # are handled together and its label can be divided among them).
        groups: dict[int, list[tuple[int, int, int]]] = {}
        for i, (top, bottom) in enumerate(new_bounds, start=1):
            groups.setdefault(_overlap_index(top, bottom, old_runs), []).append((i, top, bottom))

        for j, children in groups.items():
            _ot, _ob, status, text = old_runs[j] if j >= 0 else (0, 0, "pending", "")

            if status == "rejected":
                (out_col / "rejected").mkdir(exist_ok=True)
                for i, top, bottom in children:
                    cv2.imwrite(
                        str(out_col / "rejected" / f"line_{i:03d}.png"), _crop(image, top, bottom)
                    )
                    rec["rejected"] += 1
                continue

            for i, top, bottom in children:
                cv2.imwrite(str(out_col / f"line_{i:03d}.png"), _crop(image, top, bottom))
                rec["crops"] += 1

            if status == "pending":
                rec["pending"] += len(children)
                continue

            if len(children) == 1:  # unchanged labeled / marker line
                i = children[0][0]
                (out_col / f"line_{i:03d}.txt").write_text(text, encoding="utf-8")
                rec["carried" if status == "labeled" else "markers"] += 1
                continue

            # A labeled/marker run was split. The labeler typed fused lines
            # newline-separated, so divide the label among the children top-to-bottom.
            parts = text.rstrip("\n").split("\n")
            if not text.strip():  # empty marker (e.g. ornament band) -> empty markers
                for i, _, _ in children:
                    (out_col / f"line_{i:03d}.txt").write_text(text, encoding="utf-8")
                    rec["markers"] += 1
            elif len(parts) == len(children):  # clean 1:1 split
                for (i, _, _), part in zip(children, parts):
                    (out_col / f"line_{i:03d}.txt").write_text(part, encoding="utf-8")
                    rec["autosplit"] += 1
            else:  # part/child mismatch -> can't auto-split, flag for human
                for i, top, bottom in children:
                    rec["relabel"] += 1
                    worklist.append(
                        {
                            "page": page_id,
                            "column": col,
                            "line": i,
                            "rows": [int(top), int(bottom)],
                            "n_children": len(children),
                            "n_label_parts": len(parts),
                            "merged_label_hint": text,
                        }
                    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORKLIST.write_text(json.dumps(worklist, ensure_ascii=False, indent=2), encoding="utf-8")
    _report(pages, len(worklist))
    return 0


def _report(pages: dict[str, dict[str, int]], n_relabel: int) -> None:
    print(f"\nRe-sliced into {OUT_DIR}\n")
    hdr = ("page", "crops", "carried", "autospl", "marker", "pending", "reject", "RELABEL")
    print("{:<12}{:>7}{:>9}{:>9}{:>8}{:>9}{:>8}{:>9}".format(*hdr))
    print("-" * 72)
    tot = dict(crops=0, carried=0, autosplit=0, markers=0, pending=0, rejected=0, relabel=0)
    for page_id in sorted(pages):
        r = pages[page_id]
        for k in tot:
            tot[k] += r[k]
        mark = "  <--" if (r["autosplit"] or r["relabel"]) else ""
        print(
            f"{page_id:<12}{r['crops']:>7}{r['carried']:>9}{r['autosplit']:>9}"
            f"{r['markers']:>8}{r['pending']:>9}{r['rejected']:>8}{r['relabel']:>9}{mark}"
        )
    print("-" * 72)
    print(
        f"{'TOTAL':<12}{tot['crops']:>7}{tot['carried']:>9}{tot['autosplit']:>9}"
        f"{tot['markers']:>8}{tot['pending']:>9}{tot['rejected']:>8}{tot['relabel']:>9}"
    )
    print(
        f"\nLabels auto-split from newline-separated merged labels: {tot['autosplit']}.\n"
        f"{n_relabel} crop(s) still need a human (re)label (part/child mismatch).\n"
        f"Worklist: {WORKLIST}"
    )


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    argparse.ArgumentParser(
        description="Non-destructive re-slice of data/columns with label carry-over."
    ).parse_args()
    sys.exit(reslice())


if __name__ == "__main__":
    main()
