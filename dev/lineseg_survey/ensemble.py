"""Fill hyocr-paddle's missed lines from kraken+Surya agreement, scored against the reviews.

Rule: a kraken line that Surya *agrees* on (bbox IoU >= --agree) and that no paddle line
covers (paddle boxes cover < --covered of it) is added to paddle's lines. kraken's polygon
is used because Surya's rectangles clip ink.

Evaluation uses the human paddle reviews: each human-drawn ``missed_lines`` box is a line
paddle missed. An added line that matches one (IoU >= --match) is a recovery; an added
line that matches none is a false add (it would cost the reviewer a delete).

    python3 dev/lineseg_survey/ensemble.py [--agree 0.4] [--covered 0.3] [--match 0.3] [-v]

``--write --pages 453-643`` writes the merged geometry as tool ``paddle-filled`` (the
Phase 9 baseline). Added lines carry ``"source": "kraken-fill"`` and are slotted into
paddle's reading order (see ``insert_in_order``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def area(b: list[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a: list[float], b: list[float]) -> float:
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def iou(a: list[float], b: list[float]) -> float:
    i = inter(a, b)
    u = area(a) + area(b) - i
    return i / u if u else 0.0


def coverage(box: list[float], others: list[list[float]]) -> float:
    """Fraction of ``box`` covered by ``others`` (row-sampled, handles overlaps)."""
    if area(box) == 0:
        return 0.0
    x1, y1, x2, y2 = box
    covered, total, steps = 0.0, 0.0, 20
    for k in range(steps):
        y = y1 + (k + 0.5) * (y2 - y1) / steps
        spans = sorted((max(x1, o[0]), min(x2, o[2])) for o in others
                       if o[1] <= y <= o[3] and o[0] < x2 and o[2] > x1)
        cur_end, run = x1, 0.0
        for s, e in spans:
            s = max(s, cur_end)
            if e > s:
                run += e - s
                cur_end = e
        covered += run
        total += x2 - x1
    return covered / total


def lines(tool: str, page: int) -> list[dict]:
    return json.loads((common.tool_data_dir(tool, page) / "segmentation.json").read_text())["lines"]


def proposals(page: int, agree: float, covered: float) -> list[dict]:
    kraken, surya, paddle = (lines(t, page) for t in ("kraken", "surya", "hyocr-paddle"))
    paddle_boxes = [l["bbox"] for l in paddle]
    out = []
    for k in kraken:
        best = max((iou(k["bbox"], s["bbox"]) for s in surya), default=0.0)
        if best < agree:
            continue
        if coverage(k["bbox"], paddle_boxes) >= covered:
            continue
        out.append({**k, "agree_iou": round(best, 3)})
    return out


def insert_in_order(base: list[dict], add: dict) -> int:
    """Index at which ``add`` joins paddle's ordered ``base`` lines.

    After the lowest base line that sits above it in the same column (x-overlap), else
    before the highest base line below it in the same column, else by y over all lines.
    """
    ax1, ay1, ax2, ay2 = add["bbox"]
    acy = (ay1 + ay2) / 2

    def same_col(b: dict) -> bool:
        bx1, _, bx2, _ = b["bbox"]
        return min(ax2, bx2) - max(ax1, bx1) > 0.3 * min(ax2 - ax1, bx2 - bx1)

    def cy(b: dict) -> float:
        return (b["bbox"][1] + b["bbox"][3]) / 2

    above = [i for i, b in enumerate(base) if same_col(b) and cy(b) < acy]
    if above:
        return max(above, key=lambda i: cy(base[i])) + 1
    below = [i for i, b in enumerate(base) if same_col(b) and cy(b) >= acy]
    if below:
        return min(below, key=lambda i: cy(base[i]))
    return sum(1 for b in base if cy(b) < acy)


def write_filled(page: int, agree: float, covered: float) -> tuple[int, int]:
    seg_path = common.tool_data_dir("hyocr-paddle", page) / "segmentation.json"
    seg = json.loads(seg_path.read_text())
    merged = [dict(l) for l in seg["lines"]]
    adds = proposals(page, agree, covered)
    for a in sorted(adds, key=lambda a: (a["bbox"][1], a["bbox"][0])):
        rec = {"boundary": a["boundary"], "baseline": a["baseline"], "bbox": a["bbox"],
               "source": "kraken-fill", "kraken_id": a["id"], "agree_iou": a["agree_iou"]}
        merged.insert(insert_in_order(merged, rec), rec)
    for line in merged:
        line.setdefault("source", "hyocr-paddle")
    out = common.write_segmentation(
        "paddle-filled", page, merged, width=seg["width"], height=seg["height"],
        model=f"hyocr-paddle + kraken lines Surya agrees on (agree>={agree}, covered<{covered})",
        extra={"layout_blocks": seg.get("layout_blocks", [])},
    )
    # write_segmentation keeps only geometry + confidence/text; restore provenance fields
    rec = json.loads(out.read_text())
    for line, src in zip(rec["lines"], merged):
        for key in ("source", "kraken_id", "agree_iou"):
            if key in src:
                line[key] = src[key]
    out.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return len(seg["lines"]), len(adds)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agree", type=float, default=0.4)
    ap.add_argument("--covered", type=float, default=0.3)
    ap.add_argument("--match", type=float, default=0.3)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--write", action="store_true", help="write tool paddle-filled instead of evaluating")
    ap.add_argument("--pages", help="pages for --write, e.g. 453-643")
    args = ap.parse_args()

    if args.write:
        total_add = 0
        for page in common.parse_pages(args.pages):
            needed = [common.tool_data_dir(t, page) / "segmentation.json"
                      for t in ("hyocr-paddle", "kraken", "surya")]
            if not all(p.exists() for p in needed):
                print(f"page {page}: missing input geometry, skipped")
                continue
            n, k = write_filled(page, args.agree, args.covered)
            total_add += k
            print(f"page {page}: {n} paddle + {k} filled")
        print(f"total filled lines: {total_add}")
        return

    tot_missed = tot_rec = tot_add = tot_false = 0
    for page in common.SAMPLE_PAGES:
        if page in common.TABLE_PAGES:
            continue
        review = json.loads((common.SURVEY_DIR / "hyocr-paddle" / "reviews"
                             / f"page_{page}.review.json").read_text())
        missed = [m["box"] for m in review.get("missed_lines", [])]
        adds = proposals(page, args.agree, args.covered)
        recovered = {i for i, m in enumerate(missed)
                     if any(iou(a["bbox"], m) >= args.match for a in adds)}
        false = [a for a in adds if not any(iou(a["bbox"], m) >= args.match for m in missed)]
        tot_missed += len(missed); tot_rec += len(recovered)
        tot_add += len(adds); tot_false += len(false)
        if args.verbose or missed or adds:
            print(f"p.{page}: missed {len(missed)}, recovered {len(recovered)}; "
                  f"added {len(adds)}, false {len(false)}"
                  + ("".join(f"\n    false add {a['id']} bbox={[round(v) for v in a['bbox']]}" for a in false)
                     if args.verbose else ""))
    print(f"\nagree>={args.agree} covered<{args.covered}: recovered {tot_rec}/{tot_missed} missed lines; "
          f"{tot_add} added, {tot_false} false adds")


if __name__ == "__main__":
    main()
