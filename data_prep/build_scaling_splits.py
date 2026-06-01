"""
Snapshot a frozen 100-line test set + nested train splits for the Phase 4
CER-vs-training-size scaling experiment.

Run AFTER data_prep/build_phase4_dataset.py (which merges all 9 labeled pages
into data/phase4_dataset/). This script then:

  1. Enumerates every NON-EMPTY line under data/phase4_dataset/page_*/ as ids
     "page_XXXX/line_NNN" (same non-empty filter the trainer uses).
  2. Deterministically shuffles (seed 42 by default).
  3. Copies the first 100 into data/frozen_test_set/ as flat line_001..100.{png,txt}
     plus a manifest.json recording provenance (frozen id -> source id).
  4. From the remaining pool builds NESTED train sets 50 ⊂ 150 ⊂ 500 and writes
     data/phase4_scaling/splits_{50,150,500}.json.

The frozen test set and splits live OUTSIDE data/phase4_dataset/ so the
shutil.rmtree rebuild in build_phase4_dataset.py can't delete them.

IMPORTANT ordering: once this snapshot is taken, treat data/phase4_dataset/ as
frozen for the experiment. Re-running the merge renumbers lines and would
invalidate the ids recorded here.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PHASE4_DIR = REPO / "data/phase4_dataset"
FROZEN_DIR = REPO / "data/frozen_test_set"
SCALING_DIR = REPO / "data/phase4_scaling"

N_TEST = 100
TRAIN_SIZES = [50, 150, 500]


def enumerate_nonempty_ids() -> list[str]:
    """Every non-empty line under phase4_dataset/page_*/ as 'page_XXXX/line_NNN'.

    Mirrors GrabarLineDataset's filter: a line counts only if its .txt has
    non-whitespace content AND the sibling .png exists.
    """
    ids: list[str] = []
    for page_dir in sorted(PHASE4_DIR.glob("page_*")):
        if not page_dir.is_dir():
            continue
        for txt_path in sorted(page_dir.glob("line_*.txt")):
            text = txt_path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            if not txt_path.with_suffix(".png").exists():
                continue
            ids.append(f"{page_dir.name}/{txt_path.stem}")
    return ids


def write_frozen_test_set(test_ids: list[str], seed: int) -> None:
    """Copy each test id's png+txt into FROZEN_DIR as flat line_001..N + manifest."""
    if FROZEN_DIR.exists():
        shutil.rmtree(FROZEN_DIR)
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {"seed": seed, "n_test": len(test_ids), "lines": {}}
    for i, src_id in enumerate(test_ids, start=1):
        flat = f"line_{i:03d}"
        src_png = PHASE4_DIR / f"{src_id}.png"
        src_txt = PHASE4_DIR / f"{src_id}.txt"
        shutil.copy2(src_png, FROZEN_DIR / f"{flat}.png")
        shutil.copy2(src_txt, FROZEN_DIR / f"{flat}.txt")
        manifest["lines"][flat] = src_id
    (FROZEN_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def write_splits(train_pool: list[str], frozen_ids: list[str], seed: int, pool_size: int) -> None:
    SCALING_DIR.mkdir(parents=True, exist_ok=True)
    frozen_set = set(frozen_ids)
    for n in TRAIN_SIZES:
        train = train_pool[:n]  # nested: 50 ⊂ 150 ⊂ 500
        assert len(train) == n, f"need {n} train ids, pool only has {len(train_pool)}"
        assert set(train).isdisjoint(frozen_set), f"leakage: train_{n} overlaps frozen test set"
        splits = {
            "seed": seed,
            "n_train": n,
            "train": train,
            "frozen_test_dir": "data/frozen_test_set",
            "n_test": len(frozen_ids),
            "pool_size": pool_size,
        }
        out = SCALING_DIR / f"splits_{n}.json"
        out.write_text(json.dumps(splits, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {out.relative_to(REPO)}  (n_train={n})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42, help="shuffle seed (default 42)")
    args = parser.parse_args()

    all_ids = enumerate_nonempty_ids()
    n_all = len(all_ids)
    print(f"Found {n_all} non-empty lines under {PHASE4_DIR.relative_to(REPO)}/")

    max_train = max(TRAIN_SIZES)
    if n_all < N_TEST + max_train:
        raise SystemExit(
            f"Not enough data: need >= {N_TEST + max_train} non-empty lines "
            f"({N_TEST} test + {max_train} train), found {n_all}. "
            f"Re-run build_phase4_dataset.py to merge all labeled pages first."
        )

    rng = random.Random(args.seed)
    shuffled = all_ids[:]
    rng.shuffle(shuffled)

    frozen_ids = shuffled[:N_TEST]
    train_pool = shuffled[N_TEST:]
    pool_size = len(train_pool)

    # Hard guarantee of no leakage before we copy anything.
    assert set(frozen_ids).isdisjoint(set(train_pool)), "frozen/pool overlap (impossible split)"
    assert max_train <= pool_size, f"train pool {pool_size} < largest train size {max_train}"

    print(f"Frozen test set : {len(frozen_ids)} lines -> {FROZEN_DIR.relative_to(REPO)}/")
    write_frozen_test_set(frozen_ids, args.seed)

    print(f"Train pool      : {pool_size} lines (nested splits {TRAIN_SIZES})")
    write_splits(train_pool, frozen_ids, args.seed, pool_size)

    print("\nSummary:")
    print(f"  total non-empty lines : {n_all}")
    print(f"  frozen test set       : {len(frozen_ids)}")
    print(f"  train pool            : {pool_size}")
    print(f"  nested train sizes    : {TRAIN_SIZES}  (50 ⊂ 150 ⊂ 500)")
    print(f"  seed                  : {args.seed}")


if __name__ == "__main__":
    main()
