"""kraken (incumbent) → survey geometry.

kraken's geometry already exists for pp.448–642 (``dev/kraken_segment.py``, with the
rule-anchored gutter split applied). This copies it into the survey layout, so kraken
is reviewed in its own ``reviews/`` dir exactly like every other tool. The existing
``dev/kraken_review/reviews`` are left alone. They predate categories 4–5, and some
were saved against earlier line numbering.

Stdlib only:

    python3 dev/lineseg_survey/run_kraken.py [--pages ...]

To (re)segment a page kraken has not seen (e.g. 643), run
``dev/venv-grabar/bin/python dev/kraken_segment.py --pages 643`` first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

TOOL = "kraken"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", help="e.g. 453-643 or 457,530 (default: survey sample)")
    args = ap.parse_args()
    for page in common.parse_pages(args.pages):
        src = common.KRAKEN_DATA / f"page_{page}" / "segmentation.json"
        if not src.exists():
            print(f"page {page}: no kraken geometry, skipped")
            continue
        seg = json.loads(src.read_text(encoding="utf-8"))
        seg["tool"] = TOOL
        seg["source_image"] = str(common.render_path(page).relative_to(common.REPO_ROOT))
        out = common.tool_data_dir(TOOL, page)
        out.mkdir(parents=True, exist_ok=True)
        (out / "segmentation.json").write_text(json.dumps(seg, indent=1), encoding="utf-8")
        print(f"page {page}: {len(seg['lines'])} lines")


if __name__ == "__main__":
    main()
