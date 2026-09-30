"""Tally the human reviews into the Phase 8 §5 results table.

Reads every ``dev/lineseg_survey/<tool>/reviews/page_<N>.review.json`` and prints a
markdown table per tool. **Correction effort** is the number of ops a reviewer
needed to make the page right: flags + missed boxes + initials + merges + splits.
Section-title marks are not errors and are not counted.

    python3 dev/lineseg_survey/score.py [--pages ...] [--tools kraken,surya,...]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

CATS = {1: "over", 2: "under", 3: "non-text", 4: "clips", 5: "order"}
OPS = ("missed_lines", "initials", "merges", "splits")
DEFAULT_TOOLS = ["kraken", "surya", "hyocr-paddle", "hyocr-tess", "projection"]


def page_counts(tool: str, page: int) -> Counter | None:
    path = common.SURVEY_DIR / tool / "reviews" / f"page_{page}.review.json"
    if not path.exists():
        return None
    review = json.loads(path.read_text(encoding="utf-8"))
    c: Counter = Counter()
    for info in review.get("flags", {}).values():
        c[CATS[int(info["category"])]] += 1
    for op in OPS:
        c[op] += len(review.get(op, []))
    c["effort"] = sum(v for k, v in c.items() if k != "effort")
    seg = json.loads((common.tool_data_dir(tool, page) / "segmentation.json").read_text())
    c["lines"] = len(seg["lines"])
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", help="default: survey sample")
    ap.add_argument("--tools", default=",".join(DEFAULT_TOOLS))
    args = ap.parse_args()
    pages = common.parse_pages(args.pages)
    cols = ["lines", *CATS.values(), *OPS, "effort"]

    summary = []
    for tool in args.tools.split(","):
        rows, total = [], Counter()
        for page in pages:
            c = page_counts(tool, page)
            if c is None:
                continue
            rows.append((page, c))
            total.update(c)
        print(f"\n### {tool} — {len(rows)}/{len(pages)} pages reviewed\n")
        print("| page | " + " | ".join(cols) + " |")
        print("|---:|" + "---:|" * len(cols))
        for page, c in rows:
            print(f"| {page} | " + " | ".join(str(c[k]) for k in cols) + " |")
        if rows:
            print("| **total** | " + " | ".join(f"**{total[k]}**" for k in cols) + " |")
            summary.append((tool, len(rows), total["effort"], total["effort"] / len(rows)))

    print("\n### Correction effort per reviewed page\n")
    print("| tool | pages | total effort | effort / page |")
    print("|---|---:|---:|---:|")
    for tool, n, eff, per in sorted(summary, key=lambda r: r[3]):
        print(f"| {tool} | {n} | {eff} | {per:.1f} |")


if __name__ == "__main__":
    main()
