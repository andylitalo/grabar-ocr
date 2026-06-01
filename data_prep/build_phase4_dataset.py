"""
Assembles data/phase4_dataset/ from every labeled page, with no hand-editing.

Sources (auto-discovered):
  - data/golden/page_XXXX/   flat (line_NNN.{png,txt} directly in the page dir)
  - data/lines/page_XXXX/    column subdirs (column_1/, column_2/, ...)

Each page is flattened into a single dir data/phase4_dataset/page_XXXX/ with
sequential line numbering. Empty .txt files (section markers) are preserved —
they are excluded from CER at train time. Lines with no .txt (still pending) and
the labeling tool's column_*/rejected/ crops are skipped.

It then writes an even train/test split across ALL pages (spread by page number,
so the held-out set covers the whole book rather than a contiguous block) to
data/phase4_dataset/splits.json, which the training script reads directly.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

GOLDEN_DIR = REPO / "data/golden"
LINES_DIR = REPO / "data/lines"
OUT_BASE = REPO / "data/phase4_dataset"
SPLITS_PATH = OUT_BASE / "splits.json"

# Fraction of pages held out for the test/eval set (spread evenly across pages).
TEST_RATIO = 0.2


def discover_pages() -> list[tuple[str, Path, str]]:
    """Find every labeled page. Returns (page_name, src_dir, kind) tuples.

    kind is "flat" (lines directly in the dir) or "columns" (column_* subdirs).
    """
    found: dict[str, tuple[str, Path, str]] = {}
    for src in sorted(GOLDEN_DIR.glob("page_*")):
        if src.is_dir():
            found[src.name] = (src.name, src, "flat")
    for src in sorted(LINES_DIR.glob("page_*")):
        if src.is_dir():
            kind = "columns" if any(src.glob("column_*")) else "flat"
            found[src.name] = (src.name, src, kind)
    return [found[name] for name in sorted(found)]


def _copy_pair(png: Path, dst_dir: Path, name: str) -> bool:
    """Copy a png + its sibling .txt as <name>.{png,txt}. Skip if no .txt."""
    txt = png.with_suffix(".txt")
    if not txt.exists():
        print(f"  SKIP (pending, no .txt): {png}")
        return False
    shutil.copy2(png, dst_dir / f"{name}.png")
    shutil.copy2(txt, dst_dir / f"{name}.txt")
    return True


def copy_flat(src_dir: Path, dst_dir: Path) -> int:
    """Copy a flat page directory (no column subdirs), renumbering sequentially."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    counter = 1
    for png in sorted(src_dir.glob("line_*.png")):
        if _copy_pair(png, dst_dir, f"line_{counter:03d}"):
            counter += 1
    return counter - 1


def flatten_columns(src_page_dir: Path, dst_dir: Path) -> int:
    """Merge column_1, column_2, ... into one flat dir with sequential numbering.

    The column_*/rejected/ subdirs are not globbed (top-level only), so rejected
    crops are excluded automatically.
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    counter = 1
    for col_dir in sorted(src_page_dir.glob("column_*")):
        for png in sorted(col_dir.glob("line_*.png")):
            if _copy_pair(png, dst_dir, f"line_{counter:03d}"):
                counter += 1
    return counter - 1


def page_counts(page_dir: Path) -> tuple[int, int]:
    """(total lines, non-empty lines) for a flattened page dir."""
    txts = sorted(page_dir.glob("line_*.txt"))
    non_empty = sum(1 for t in txts if t.read_text(encoding="utf-8").strip())
    return len(txts), non_empty


def even_test_pages(pages: list[str], test_ratio: float) -> list[str]:
    """Pick test pages spread evenly across the (sorted) page list.

    Selecting positions (k+0.5)*n/n_test keeps held-out pages distributed over
    the whole book instead of clustered at one end. Always leaves >=1 train page.
    """
    n = len(pages)
    if n <= 1:
        return []
    n_test = min(max(1, round(n * test_ratio)), n - 1)
    idx = sorted({int((k + 0.5) * n / n_test) for k in range(n_test)})
    return [pages[i] for i in idx]


def main() -> None:
    if OUT_BASE.exists():
        shutil.rmtree(OUT_BASE)  # clean rebuild so removed lines never linger
    OUT_BASE.mkdir(parents=True, exist_ok=True)

    discovered = discover_pages()
    if not discovered:
        print("No labeled pages found under data/golden/ or data/lines/.")
        return

    counts: dict[str, dict[str, int]] = {}
    for name, src, kind in discovered:
        dst = OUT_BASE / name
        n = copy_flat(src, dst) if kind == "flat" else flatten_columns(src, dst)
        total, non_empty = page_counts(dst)
        counts[name] = {"lines": total, "non_empty": non_empty}
        print(f"{name}: {n} lines flattened from {kind} ({non_empty} non-empty)")

    pages = sorted(counts)
    test = even_test_pages(pages, TEST_RATIO)
    train = [p for p in pages if p not in test]

    splits = {
        "test_ratio": TEST_RATIO,
        "train": train,
        "test": test,
        "counts": counts,
        "totals": {
            "train_non_empty": sum(counts[p]["non_empty"] for p in train),
            "test_non_empty": sum(counts[p]["non_empty"] for p in test),
            "all_non_empty": sum(c["non_empty"] for c in counts.values()),
        },
    }
    SPLITS_PATH.write_text(json.dumps(splits, indent=2), encoding="utf-8")

    t = splits["totals"]
    print(f"\nDataset summary ({len(pages)} pages, {t['all_non_empty']} non-empty lines):")
    print(f"  train: {train}  ({t['train_non_empty']} non-empty)")
    print(f"  test : {test}  ({t['test_non_empty']} non-empty)")
    print(f"  wrote {SPLITS_PATH.relative_to(REPO)}")


if __name__ == "__main__":
    main()
