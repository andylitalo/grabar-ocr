"""
detect_nonchar_lines.py — the non-character-line phase gate (report-only).

Scans the line crops the OCR model would see (data/lines/<page>/column_*/line_*.png),
computes image-level features (data_prep.line_filter), classifies each line as text
vs. non-character (ornamental divider / blank speck), and writes an auditable report
WITHOUT touching predictions or data. A human then confirms every flagged line is
genuinely non-text and that no real line is flagged — that is the gate.

Outputs (under reports/):
  nonchar_flagged.csv   — every line, its features, and flag/reason
  nonchar_flagged.html  — per-page contact sheet: flagged lines (red) plus the
                          highest-ink UNFLAGGED lines (green) so the safety margin
                          to the nearest real line is visible at a glance.

Run (BASE env — cv2 + numpy, no torch):
    .venv/bin/python data_prep/detect_nonchar_lines.py
    .venv/bin/python data_prep/detect_nonchar_lines.py --pages page_0487_auto
    .venv/bin/python data_prep/detect_nonchar_lines.py --ink-factor 1.7 --use-repetition
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from html import escape
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from data_prep.line_filter import (  # noqa: E402
    DEFAULT_INK_FACTOR,
    classify_page,
    line_features,
    ocr_is_repetitive,
    page_median_ink,
)
from labeling_ui import storage  # noqa: E402

REPORTS = REPO / "reports"
BORDERLINE_PER_PAGE = 5  # highest-ink unflagged lines shown to expose the margin


def discover_pages() -> list[str]:
    """All page ids under data/lines/ that have a column_*/ subdir."""
    if not storage.DATA_LINES.is_dir():
        return []
    pages = []
    for d in sorted(storage.DATA_LINES.iterdir()):
        if d.is_dir() and any(d.glob("column_*")):
            pages.append(d.name)
    return pages


def page_line_crops(page_id: str) -> list[tuple[str, int, Path]]:
    """(line_id, column, png) for placed line crops, in reading order.

    Mirrors predict_lines.collect_page: placed crops only (not rejected/), sorted
    column_1 then column_2, so the gate sees exactly what OCR would.
    """
    out: list[tuple[str, int, Path]] = []
    page_dir = storage.DATA_LINES / page_id
    for col_dir in sorted(page_dir.glob("column_*")):
        col = int(col_dir.name.split("_")[1])
        for png in sorted(col_dir.glob("line_*.png")):
            out.append((f"column_{col}/{png.stem}", col, png))
    return out


def load_ocr_text(page_id: str) -> dict[str, str]:
    """Beam OCR text per line if a prediction set exists (for the repetition fallback)."""
    _, preds = storage.page_predictions(page_id)
    return preds


def analyze_page(page_id: str, ink_factor: float, use_repetition: bool) -> dict:
    """Compute features, classify, and assemble per-line records for one page."""
    crops = page_line_crops(page_id)
    features: dict[str, dict] = {}
    cols: dict[str, int] = {}
    pngs: dict[str, Path] = {}
    for line_id, col, png in crops:
        gray = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
        features[line_id] = line_features(gray)
        cols[line_id] = col
        pngs[line_id] = png

    median = page_median_ink(features)
    flagged = classify_page(features, ink_factor=ink_factor)

    ocr = load_ocr_text(page_id) if use_repetition else {}
    rows: list[dict] = []
    for line_id, f in features.items():
        ink_ratio = f["ink_density"] / median if median else 0.0
        text = ocr.get(line_id, "")
        rep = use_repetition and bool(text) and ocr_is_repetitive(text)
        is_nc = flagged[line_id] or rep
        reasons = []
        if f["glyph_count"] == 0:
            reasons.append("no_glyphs")
        if median and f["ink_density"] > ink_factor * median:
            reasons.append("high_ink")
        if rep:
            reasons.append("ocr_repetitive")
        rows.append(
            {
                "page": page_id,
                "line_id": line_id,
                "column": cols[line_id],
                "glyph_count": f["glyph_count"],
                "n_components": f["n_components"],
                "height": f["height"],
                "ink_density": f["ink_density"],
                "ink_ratio": ink_ratio,
                "flagged": is_nc,
                "reason": "+".join(reasons),
                "ocr_text": text,
                "png": pngs[line_id],
            }
        )
    return {"page": page_id, "median_ink": median, "rows": rows}


def write_csv(pages: list[dict], path: Path) -> None:
    cols = ["page", "line_id", "column", "glyph_count", "n_components", "height",
            "ink_density", "ink_ratio", "flagged", "reason", "ocr_text"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for pg in pages:
            for r in pg["rows"]:
                w.writerow({
                    **{k: r[k] for k in cols if k not in ("ink_density", "ink_ratio")},
                    "ink_density": f"{r['ink_density']:.4f}",
                    "ink_ratio": f"{r['ink_ratio']:.3f}",
                })


def _card(r: dict, kind: str) -> str:
    img = "../" + r["png"].relative_to(REPO).as_posix()
    ocr = f"<div class=ocr><b>OCR</b> {escape(r['ocr_text'])}</div>" if r["ocr_text"] else ""
    return (
        f"<div class='card {kind}'>"
        f"<img src='{escape(img)}' />"
        f"<div class=meta>{escape(r['line_id'])} · glyph {r['glyph_count']} · "
        f"ink {r['ink_density']:.4f} ({r['ink_ratio']:.2f}×) · h{r['height']}"
        f"{' · ' + escape(r['reason']) if r['reason'] else ''}</div>"
        f"{ocr}</div>"
    )


def write_html(pages: list[dict], path: Path, ink_factor: float) -> None:
    total = sum(len(pg["rows"]) for pg in pages)
    n_flag = sum(1 for pg in pages for r in pg["rows"] if r["flagged"])
    sections = []
    for pg in pages:
        flagged = [r for r in pg["rows"] if r["flagged"]]
        unflagged = [r for r in pg["rows"] if not r["flagged"]]
        borderline = sorted(unflagged, key=lambda r: -r["ink_ratio"])[:BORDERLINE_PER_PAGE]
        flag_cards = "".join(_card(r, "flag") for r in flagged) or "<p class=sanity>(none flagged)</p>"
        border_cards = "".join(_card(r, "keep") for r in borderline)
        sections.append(
            f"<h2>{escape(pg['page'])} <span class=sanity>· {len(pg['rows'])} lines · "
            f"median ink {pg['median_ink']:.4f} · flagged {len(flagged)}</span></h2>"
            f"<h3>Flagged non-character ({len(flagged)}) — confirm each is genuinely non-text</h3>"
            f"<div class=grid>{flag_cards}</div>"
            f"<h3>Highest-ink REAL lines kept ({len(borderline)}) — confirm none should be flagged</h3>"
            f"<div class=grid>{border_cards}</div>"
        )

    html = f"""<!doctype html><meta charset=utf-8>
<title>Non-character line detection</title>
<style>
 body {{ font-family:-apple-system,system-ui,sans-serif; background:#15161a; color:#e8e8ec; margin:1.5rem; }}
 h1 {{ font-size:1.25rem; }} h2 {{ font-size:1.05rem; margin-top:1.6rem; border-top:1px solid #3a3d46; padding-top:.8rem; }}
 h3 {{ font-size:.9rem; color:#cfd2da; margin:.9rem 0 .3rem; }}
 .sanity {{ color:#9aa0ac; font-weight:normal; }}
 .grid {{ display:flex; flex-wrap:wrap; gap:.5rem; }}
 .card {{ background:#2a2c33; border:1px solid #3a3d46; border-radius:8px; padding:.5rem; max-width:420px; }}
 .card.flag {{ border-left:4px solid #d9534f; }}
 .card.keep {{ border-left:4px solid #4ec77a; }}
 .card img {{ background:#f4f4f4; max-width:100%; display:block; padding:4px; border-radius:4px; }}
 .meta {{ color:#9aa0ac; font-size:.78rem; margin:.3rem 0; }}
 .ocr {{ font-size:1rem; color:#bfe3ff; }} .ocr b {{ color:#9aa0ac; font-size:.7rem; }}
</style>
<h1>Non-character line detection — gate review</h1>
<p>{n_flag} flagged / {total} lines across {len(pages)} page(s) · INK_FACTOR = {ink_factor}
 · rule: <code>glyph_count == 0 OR ink &gt; {ink_factor}× page-median</code></p>
<p class=sanity>Gate passes when every red card is genuinely non-text AND no green card should have been flagged.</p>
{''.join(sections)}
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", help="comma-separated page ids (default: all under data/lines/)")
    ap.add_argument("--ink-factor", type=float, default=DEFAULT_INK_FACTOR,
                    help=f"ink-density multiple over page median to flag (default {DEFAULT_INK_FACTOR})")
    ap.add_argument("--use-repetition", action="store_true",
                    help="also flag lines whose OCR output is a short repeated unit (needs predictions)")
    args = ap.parse_args()

    page_ids = args.pages.split(",") if args.pages else discover_pages()
    if not page_ids:
        raise SystemExit("No pages found under data/lines/.")

    pages = [analyze_page(p, args.ink_factor, args.use_repetition) for p in page_ids]

    REPORTS.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS / "nonchar_flagged.csv"
    html_path = REPORTS / "nonchar_flagged.html"
    write_csv(pages, csv_path)
    write_html(pages, html_path, args.ink_factor)

    total = sum(len(pg["rows"]) for pg in pages)
    n_flag = sum(1 for pg in pages for r in pg["rows"] if r["flagged"])
    print(f"\nNon-character line detection (INK_FACTOR={args.ink_factor}"
          f"{', +repetition' if args.use_repetition else ''})")
    print(f"  {n_flag} flagged / {total} lines across {len(pages)} page(s)\n")
    print(f"  {'page':18} {'lines':>5} {'flag':>4}  flagged line ids")
    for pg in pages:
        flagged = [r for r in pg["rows"] if r["flagged"]]
        ids = ", ".join(r["line_id"] for r in flagged)
        print(f"  {pg['page']:18} {len(pg['rows']):5d} {len(flagged):4d}  {ids}")
    print(f"\n  wrote {csv_path.relative_to(REPO)}")
    print(f"  wrote {html_path.relative_to(REPO)}  (open and confirm the gate)")


if __name__ == "__main__":
    main()
