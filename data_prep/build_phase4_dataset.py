"""
Assembles data/phase4_dataset/ from:
  - data/golden/page_0335/  (Phase 0, flat)
  - data/lines/page_0543/   (new, column subdirs)
  - data/lines/page_0559/   (new, column subdirs)

Column subdirs are merged into a single flat page dir with sequential line numbering.
Empty .txt files (section markers) are preserved — they are excluded from CER at train time.
"""

import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

GOLDEN_SRC = REPO / "data/golden/page_0335"
NEW_PAGES = [
    REPO / "data/lines/page_0543",
    REPO / "data/lines/page_0559",
]
OUT_BASE = REPO / "data/phase4_dataset"


def copy_flat(src_dir: Path, dst_dir: Path) -> int:
    """Copy a flat page directory (no column subdirs) as-is."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for png in sorted(src_dir.glob("*.png")):
        shutil.copy2(png, dst_dir / png.name)
        txt = png.with_suffix(".txt")
        shutil.copy2(txt, dst_dir / txt.name)
        count += 1
    return count


def flatten_columns(src_page_dir: Path, dst_dir: Path) -> int:
    """Merge column_1, column_2, ... into a single flat dir with sequential numbering."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    columns = sorted(src_page_dir.glob("column_*"))
    counter = 1
    for col_dir in columns:
        for png in sorted(col_dir.glob("*.png")):
            name = f"line_{counter:03d}"
            shutil.copy2(png, dst_dir / f"{name}.png")
            txt = png.with_suffix(".txt")
            shutil.copy2(txt, dst_dir / f"{name}.txt")
            counter += 1
    return counter - 1


def pairing_check(page_dir: Path) -> None:
    missing = [p for p in sorted(page_dir.glob("*.png")) if not p.with_suffix(".txt").exists()]
    if missing:
        for m in missing:
            print(f"  MISSING TXT: {m}")
    else:
        print(f"  OK — all PNGs have matching TXTs")


if __name__ == "__main__":
    # Phase 0 golden page
    dst = OUT_BASE / "page_0335"
    n = copy_flat(GOLDEN_SRC, dst)
    print(f"page_0335: copied {n} lines (flat)")
    pairing_check(dst)

    # New labeled pages
    for src in NEW_PAGES:
        page_name = src.name
        dst = OUT_BASE / page_name
        n = flatten_columns(src, dst)
        print(f"{page_name}: flattened {n} lines from columns")
        pairing_check(dst)

    print("\nDataset summary:")
    for page_dir in sorted(OUT_BASE.glob("page_*")):
        pngs = list(page_dir.glob("*.png"))
        txts = list(page_dir.glob("*.txt"))
        non_empty = [t for t in txts if t.read_text(encoding="utf-8").strip()]
        print(f"  {page_dir.name}: {len(pngs)} lines ({len(non_empty)} non-empty)")
