"""How much of a tool's "clips ink" (flag 4) would a uniform vertical pad fix?

Clipping that one fixed pad cures is a code fix, not Phase 9 reviewer work, so the
survey reports effort both raw and with those flags discounted. The same pad is applied
to every tool so the comparison stays fair.

For each line, "need" is how many rows past the top/bottom edge still carry ink inside
the line's x-range before the first blank row (capped at ``--search``). A flagged line is
"cured" by pad P if both its needs are <= P. The measure is crude: with tight leading
there is no blank row between lines, so need hits the cap. It is an estimate.

    dev/lineseg_survey/.venv-surya/bin/python dev/lineseg_survey/clip_padding.py --tool surya [--pad 8]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

INK = 128      # gray < INK counts as ink
INSET = 3      # px trimmed from each side of the x-range (ignores neighbours' edges)
TABLE_PAGES = {641}  # Paschal table: cell-level, scored apart


def needs(ink: np.ndarray, bbox: list[float], search: int) -> tuple[int, int]:
    h = ink.shape[0]
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    x1, x2 = x1 + INSET, max(x1 + INSET + 1, x2 - INSET)

    def run(edge: int, step: int) -> int:
        d = 0
        while d < search:
            y = edge + step * (d + 1)
            if y < 0 or y >= h or not ink[y, x1:x2].any():
                break
            d += 1
        return d

    return run(y1, -1), run(y2, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True)
    ap.add_argument("--pad", type=int, default=8)
    ap.add_argument("--search", type=int, default=60)
    args = ap.parse_args()

    flagged = cured = 0
    for page in common.SAMPLE_PAGES:
        if page in TABLE_PAGES:
            continue
        rev_path = common.SURVEY_DIR / args.tool / "reviews" / f"page_{page}.review.json"
        if not rev_path.exists():
            continue
        review = json.loads(rev_path.read_text())
        if review.get("status") != "reviewed":
            continue
        seg = json.loads((common.tool_data_dir(args.tool, page) / "segmentation.json").read_text())
        bbox = {line["id"]: line["bbox"] for line in seg["lines"]}
        ink = np.array(Image.open(common.render_path(page)).convert("L")) < INK
        for line_id, info in review["flags"].items():
            if 4 not in (info.get("categories") or [info.get("category")]):
                continue
            flagged += 1
            top, bottom = needs(ink, bbox[line_id], args.search)
            cured += top <= args.pad and bottom <= args.pad
    pct = 100 * cured / flagged if flagged else 0.0
    print(f"{args.tool}: {cured}/{flagged} clip flags ({pct:.0f}%) cured by a uniform {args.pad}px pad "
          f"(pages other than {sorted(TABLE_PAGES)})")


if __name__ == "__main__":
    main()
