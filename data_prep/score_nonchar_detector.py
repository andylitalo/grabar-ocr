"""
score_nonchar_detector.py — the Phase A gate report for the non-character detector.

Reads every human-verified truth file (data/lines/*_auto/nonchar_truth.json, written
by the labeling UI's verify-non-character mode) and scores the pre-OCR detector
against the human verdicts. Positive class = non-character.

  TP = detector flagged   AND human says non-character (empty)
  FP = detector flagged   AND human says character        <-- MUST be 0 (hard gate)
  FN = detector missed    AND human says non-character
  TN = detector negative  AND human says character

Reports precision / recall / F1 per page and overall, and enumerates every FP and
FN as a thumbnail card so each disagreement is inspectable. Report-only — touches
no data, no predictions, no APIs.

Outputs (under reports/):
  nonchar_detector_score.csv   — one row per verified line
  nonchar_detector_score.html  — per-page metrics + FP/FN contact sheet (the gate)
  nonchar_detector_score.md    — terse summary for the phase doc

Run (BASE env — no torch needed):
    .venv/bin/python data_prep/score_nonchar_detector.py
    uv run python data_prep/score_nonchar_detector.py
"""

from __future__ import annotations

import csv
import json
import sys
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from labeling_ui import storage  # noqa: E402

REPORTS = REPO / "reports"


def discover_truth_pages() -> list[str]:
    """Page ids under data/lines/ that have a saved nonchar_truth.json."""
    if not storage.DATA_LINES.is_dir():
        return []
    return [
        d.name
        for d in sorted(storage.DATA_LINES.iterdir())
        if d.is_dir() and (d / "nonchar_truth.json").exists()
    ]


def score_page(page_id: str) -> dict:
    """Confusion matrix + per-line rows for one verified page."""
    truth = storage.load_nonchar_truth(page_id)
    lines = truth.get("lines", {}) if truth else {}
    rows: list[dict] = []
    tp = fp = fn = tn = 0
    for line_id, rec in sorted(lines.items()):
        det = bool(rec.get("detector_nonchar", False))
        human_nonchar = rec.get("truth") == "empty"
        if det and human_nonchar:
            outcome = "TP"; tp += 1
        elif det and not human_nonchar:
            outcome = "FP"; fp += 1
        elif not det and human_nonchar:
            outcome = "FN"; fn += 1
        else:
            outcome = "TN"; tn += 1
        rows.append(
            {
                "page": page_id,
                "line_id": line_id,
                "truth": rec.get("truth"),
                "detector_nonchar": det,
                "outcome": outcome,
                "glyph_count": rec.get("glyph_count"),
                "ink_ratio": rec.get("ink_ratio"),
            }
        )
    return {
        "page": page_id,
        "rows": rows,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": _safe_div(tp, tp + fp),
        "recall": _safe_div(tp, tp + fn),
        "f1": _f1(tp, fp, fn),
    }


def _safe_div(num: int, den: int) -> float | None:
    return num / den if den else None


def _f1(tp: int, fp: int, fn: int) -> float | None:
    p = _safe_div(tp, tp + fp)
    r = _safe_div(tp, tp + fn)
    if p is None or r is None or (p + r) == 0:
        return None
    return 2 * p * r / (p + r)


def _line_png(page_id: str, line_id: str) -> Path | None:
    """Resolve column_Y/line_NNN -> the placed crop path, if present."""
    col_dir, stem = line_id.split("/", 1)
    col = int(col_dir.split("_")[1])
    line = int(stem.split("_")[1])
    return storage.line_image_path(page_id, col, line)


def write_csv(pages: list[dict], path: Path) -> None:
    cols = ["page", "line_id", "truth", "detector_nonchar", "outcome",
            "glyph_count", "ink_ratio"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for pg in pages:
            for r in pg["rows"]:
                w.writerow(r)


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _card(page_id: str, r: dict) -> str:
    png = _line_png(page_id, r["line_id"])
    img = ("../" + png.relative_to(REPO).as_posix()) if png else ""
    img_tag = f"<img src='{escape(img)}' />" if img else "<div class=missing>(image missing)</div>"
    ink = f"{r['ink_ratio']:.2f}×" if isinstance(r.get("ink_ratio"), (int, float)) else "—"
    glyph = r["glyph_count"] if r.get("glyph_count") is not None else "—"
    return (
        f"<div class='card {r['outcome']}'>"
        f"{img_tag}"
        f"<div class=meta>{escape(r['line_id'])} · {r['outcome']} · "
        f"human={escape(str(r['truth']))} · glyph {glyph} · ink {ink}</div>"
        f"</div>"
    )


def write_html(pages: list[dict], totals: dict, path: Path) -> None:
    sections = []
    for pg in pages:
        fps = [r for r in pg["rows"] if r["outcome"] == "FP"]
        fns = [r for r in pg["rows"] if r["outcome"] == "FN"]
        fp_cards = "".join(_card(pg["page"], r) for r in fps) or "<p class=sanity>(no false positives)</p>"
        fn_cards = "".join(_card(pg["page"], r) for r in fns) or "<p class=sanity>(no false negatives)</p>"
        sections.append(
            f"<h2>{escape(pg['page'])} <span class=sanity>· {len(pg['rows'])} lines · "
            f"P {_pct(pg['precision'])} · R {_pct(pg['recall'])} · F1 {_pct(pg['f1'])} · "
            f"TP {pg['tp']} FP {pg['fp']} FN {pg['fn']} TN {pg['tn']}</span></h2>"
            f"<h3>False positives ({len(fps)}) — real lines wrongly flagged (gate fails if any)</h3>"
            f"<div class=grid>{fp_cards}</div>"
            f"<h3>False negatives ({len(fns)}) — non-character lines the detector missed</h3>"
            f"<div class=grid>{fn_cards}</div>"
        )

    gate = "PASS" if totals["fp"] == 0 else "FAIL"
    gate_color = "#4ec77a" if totals["fp"] == 0 else "#d9534f"
    html = f"""<!doctype html><meta charset=utf-8>
<title>Non-character detector — Phase A gate score</title>
<style>
 body {{ font-family:-apple-system,system-ui,sans-serif; background:#15161a; color:#e8e8ec; margin:1.5rem; }}
 h1 {{ font-size:1.3rem; }} h2 {{ font-size:1.05rem; margin-top:1.6rem; border-top:1px solid #3a3d46; padding-top:.8rem; }}
 h3 {{ font-size:.9rem; color:#cfd2da; margin:.9rem 0 .3rem; }}
 .sanity {{ color:#9aa0ac; font-weight:normal; }}
 .gate {{ font-size:1.1rem; font-weight:700; color:{gate_color}; }}
 .grid {{ display:flex; flex-wrap:wrap; gap:.5rem; }}
 .card {{ background:#2a2c33; border:1px solid #3a3d46; border-radius:8px; padding:.5rem; max-width:420px; }}
 .card.FP {{ border-left:4px solid #d9534f; }}
 .card.FN {{ border-left:4px solid #e0a64f; }}
 .card img {{ background:#f4f4f4; max-width:100%; display:block; padding:4px; border-radius:4px; }}
 .missing {{ color:#9aa0ac; font-style:italic; }}
 .meta {{ color:#9aa0ac; font-size:.78rem; margin:.3rem 0; }}
 code {{ background:#2a2c33; padding:.1rem .3rem; border-radius:4px; }}
</style>
<h1>Non-character detector — Phase A gate score</h1>
<p>{len(pages)} verified page(s) · {totals['n']} lines · positive class = non-character ·
 rule <code>glyph_count==0 OR ink&gt;1.6× page-median</code></p>
<p class=gate>Gate: {gate} &nbsp;<span class=sanity>(hard gate = 0 false positives)</span></p>
<p>Overall: precision {_pct(totals['precision'])} · recall {_pct(totals['recall'])} ·
 F1 {_pct(totals['f1'])} · TP {totals['tp']} · FP {totals['fp']} · FN {totals['fn']} · TN {totals['tn']}</p>
{''.join(sections)}
"""
    path.write_text(html, encoding="utf-8")


def write_md(pages: list[dict], totals: dict, path: Path) -> None:
    gate = "PASS ✅" if totals["fp"] == 0 else "FAIL ❌"
    lines = [
        "# Non-character detector — Phase A gate score",
        "",
        f"**Gate (0 false positives): {gate}**",
        "",
        f"Overall across {len(pages)} verified page(s), {totals['n']} lines: "
        f"precision {_pct(totals['precision'])}, recall {_pct(totals['recall'])}, "
        f"F1 {_pct(totals['f1'])} "
        f"(TP {totals['tp']}, FP {totals['fp']}, FN {totals['fn']}, TN {totals['tn']}).",
        "",
        "| page | lines | precision | recall | F1 | TP | FP | FN | TN |",
        "|------|------:|----------:|-------:|---:|---:|---:|---:|---:|",
    ]
    for pg in pages:
        lines.append(
            f"| {pg['page']} | {len(pg['rows'])} | {_pct(pg['precision'])} | "
            f"{_pct(pg['recall'])} | {_pct(pg['f1'])} | {pg['tp']} | {pg['fp']} | "
            f"{pg['fn']} | {pg['tn']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def aggregate(pages: list[dict]) -> dict:
    tp = sum(p["tp"] for p in pages)
    fp = sum(p["fp"] for p in pages)
    fn = sum(p["fn"] for p in pages)
    tn = sum(p["tn"] for p in pages)
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn, "n": tp + fp + fn + tn,
        "precision": _safe_div(tp, tp + fp),
        "recall": _safe_div(tp, tp + fn),
        "f1": _f1(tp, fp, fn),
    }


def main() -> None:
    page_ids = discover_truth_pages()
    if not page_ids:
        raise SystemExit(
            "No nonchar_truth.json found under data/lines/*_auto/.\n"
            "Verify some auto pages first (labeling UI → 'Verify auto slice')."
        )

    pages = [score_page(p) for p in page_ids]
    totals = aggregate(pages)

    REPORTS.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS / "nonchar_detector_score.csv"
    html_path = REPORTS / "nonchar_detector_score.html"
    md_path = REPORTS / "nonchar_detector_score.md"
    write_csv(pages, csv_path)
    write_html(pages, totals, html_path)
    write_md(pages, totals, md_path)

    gate = "PASS" if totals["fp"] == 0 else "FAIL"
    print(f"\nNon-character detector — Phase A gate score")
    print(f"  {len(pages)} verified page(s) · {totals['n']} lines")
    print(f"  precision {_pct(totals['precision'])} · recall {_pct(totals['recall'])} "
          f"· F1 {_pct(totals['f1'])}")
    print(f"  TP {totals['tp']} · FP {totals['fp']} · FN {totals['fn']} · TN {totals['tn']}")
    print(f"  GATE (0 false positives): {gate}")
    print()
    print(f"  {'page':20} {'P':>6} {'R':>6} {'FP':>3} {'FN':>3}")
    for pg in pages:
        print(f"  {pg['page']:20} {_pct(pg['precision']):>6} {_pct(pg['recall']):>6} "
              f"{pg['fp']:3d} {pg['fn']:3d}")
    print(f"\n  wrote {csv_path.relative_to(REPO)}")
    print(f"  wrote {html_path.relative_to(REPO)}  (open: the gate artifact)")
    print(f"  wrote {md_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
