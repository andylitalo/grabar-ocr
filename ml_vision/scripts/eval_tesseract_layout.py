"""
Phase 2 follow-up — hye-tesseract LAYOUT exploration (column- and page-level).

Unlike predict_lines_tesseract.py (one prediction per pre-sliced line crop), this
asks whether Tesseract can do the segmentation ITSELF: feed it a whole column crop
or a whole deskewed page and let its layout analysis find the lines (and, for full
pages, the two-column reading order). Each run yields one text blob, not per-line
predictions, so it can't reuse the per-line report — this is a self-contained
scorer.

CER here is a LOOSER comparison than the line-level head-to-head: reading-order and
line-segmentation mistakes fold into the character error rate. So it answers "can
Tesseract handle the layout at all?", not a strict per-line accuracy comparison.

Reference (per page): the human ground-truth lines concatenated in reading order —
column_1/line_*.txt then column_2/line_*.txt (numeric sort), skipping empty
section-marker .txts. Whitespace is collapsed on BOTH reference and hypothesis
before scoring, so we measure character recognition rather than exact line breaks.

Hypotheses per page:
  column-level: tesseract on data/columns/page_XXXX_human_column_{1,2}.png,
                concatenated col1+col2 — PSM 4 (single column) and PSM 6 (uniform block).
  page-level:   tesseract on data/_labeling_work/page_XXXX/page_deskew.png —
                PSM 3 (full auto layout) and PSM 1 (auto + OSD). Tesseract chooses
                the column order itself.

Output: reports/phase2_tesseract_layout.{csv,md}
  rows = (page, level, psm, cer, n_ref_chars), plus a short markdown summary.

Run (ML env, needs pytesseract + jiwer):
    .venv_ml/bin/python ml_vision/scripts/eval_tesseract_layout.py
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import jiwer
import pytesseract
from PIL import Image

REPO = Path(__file__).resolve().parent.parent.parent
TESSDATA = REPO / "ml_vision/tessdata"
LANG = "hye-calfa-n"
LINES_DIR = REPO / "data/lines"
COLUMNS_DIR = REPO / "data/columns"
LABELING_DIR = REPO / "data/_labeling_work"
REPORTS = REPO / "reports"

DEFAULT_PAGES = ["page_0400", "page_0499", "page_0251", "page_0550"]
COLUMN_PSMS = [4, 6]
PAGE_PSMS = [3, 1]


def norm(s: str) -> str:
    """Collapse all whitespace runs to single spaces so CER measures characters,
    not line-break placement. Applied identically to reference and hypothesis."""
    return re.sub(r"\s+", " ", s).strip()


def reference_text(page: str) -> str:
    """Human GT lines in reading order: col1 then col2, numeric line sort,
    skipping empty section-marker .txts."""
    page_dir = LINES_DIR / f"{page}_human"
    parts: list[str] = []
    for col in (1, 2):
        col_dir = page_dir / f"column_{col}"
        if not col_dir.is_dir():
            continue
        for txt in sorted(col_dir.glob("line_*.txt"), key=lambda p: int(re.search(r"\d+", p.stem).group())):
            content = txt.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
    return "\n".join(parts)


def run_tesseract(img_path: Path, psm: int) -> str:
    config = f"--psm {psm} --dpi 300 --tessdata-dir {TESSDATA}"
    return pytesseract.image_to_string(Image.open(img_path).convert("RGB"), lang=LANG, config=config).strip()


def column_hypothesis(page: str, psm: int) -> str:
    blobs = []
    for col in (1, 2):
        p = COLUMNS_DIR / f"{page}_human_column_{col}.png"
        if p.exists():
            blobs.append(run_tesseract(p, psm))
    return "\n".join(blobs)


def page_hypothesis(page: str, psm: int) -> str:
    p = LABELING_DIR / page / "page_deskew.png"
    if not p.exists():
        return ""
    return run_tesseract(p, psm)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", nargs="+", default=DEFAULT_PAGES,
                        help="page stems without _human (default: %(default)s)")
    args = parser.parse_args()

    if not (TESSDATA / f"{LANG}.traineddata").exists():
        raise SystemExit(f"Missing {LANG}.traineddata under {TESSDATA.relative_to(REPO)} (see plan §Setup).")

    rows: list[dict] = []
    for page in args.pages:
        ref = reference_text(page)
        ref_n = norm(ref)
        if not ref_n:
            print(f"!! {page}: no reference GT found, skipping")
            continue
        n_ref_chars = len(ref_n)
        print(f"\n== {page} == (ref {n_ref_chars} chars)")

        for psm in COLUMN_PSMS:
            hyp = norm(column_hypothesis(page, psm))
            cer = jiwer.cer(ref_n, hyp) if hyp else 1.0
            rows.append({"page": page, "level": "column", "psm": psm,
                         "cer": cer, "n_ref_chars": n_ref_chars})
            print(f"  column psm={psm:<2} CER {cer*100:5.1f}%")

        for psm in PAGE_PSMS:
            hyp = norm(page_hypothesis(page, psm))
            cer = jiwer.cer(ref_n, hyp) if hyp else 1.0
            rows.append({"page": page, "level": "page", "psm": psm,
                         "cer": cer, "n_ref_chars": n_ref_chars})
            print(f"  page   psm={psm:<2} CER {cer*100:5.1f}%")

    REPORTS.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS / "phase2_tesseract_layout.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["page", "level", "psm", "cer", "n_ref_chars"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "cer": f"{r['cer']:.4f}"})

    # Best config per (page, level) for a compact markdown summary.
    md = ["# Phase 2 — hye-tesseract layout exploration", "",
          "Column/page CER is a *looser* comparison than the line-level head-to-head: "
          "reading-order and line-segmentation errors fold into CER. It answers "
          "\"can Tesseract handle layout at all?\", not strict per-line accuracy.", "",
          "| page | level | psm | CER | n_ref_chars |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["page"], r["level"], r["psm"])):
        md.append(f"| {r['page']} | {r['level']} | {r['psm']} | {r['cer']*100:.1f}% | {r['n_ref_chars']} |")
    md.append("")
    md.append("## Best CER per page/level")
    md.append("")
    md.append("| page | level | best psm | best CER |")
    md.append("|---|---|---|---|")
    by_group: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["page"], r["level"])
        if key not in by_group or r["cer"] < by_group[key]["cer"]:
            by_group[key] = r
    for (page, level), r in sorted(by_group.items()):
        md.append(f"| {page} | {level} | {r['psm']} | {r['cer']*100:.1f}% |")
    md.append("")
    (REPORTS / "phase2_tesseract_layout.md").write_text("\n".join(md), encoding="utf-8")

    print(f"\nwrote reports/phase2_tesseract_layout.{{csv,md}}  ({len(rows)} rows)")


if __name__ == "__main__":
    main()
