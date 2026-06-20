"""
Per-line error analysis for a Phase 4 prediction pass.

Reads predictions written by predict_lines.py (one inference pass, three
consumers) and the matching ground truth, then reports WHAT the model gets wrong
and WHETHER errors cluster by page / line length / notation. Read-only: it never
runs the model — run predict_lines.py first.

  --frozen          GT from data/frozen_test_set/line_NNN.txt; source page joined
                    from data/frozen_test_set/manifest.json (so each line carries
                    the scanned page it came from).
  --page page_XXXX_M  GT from data/lines/page_XXXX_M/column_Y/line_NNN.txt
                    (M = human|auto; the slice method rides on the page id — see data/README.md).

Per line (sorted worst-CER-first): id, source_page, column, cer (beam), cer_greedy,
ref_len, n_sub, n_del, n_ins, has_numeral, has_abbrev_mark, ref, pred_greedy,
pred_beam. CER and the S/D/I taxonomy use jiwer.

Outputs (under reports/):
  frozen: phase4_error_analysis_frozen.{csv,json,html}
  page:   phase4_newpage_<page>.{csv,json,html}
The HTML is a contact sheet of the worst-N lines (crop + ref/pred/CER) so font
and notation can be eyeballed directly.

Run (ML env, needs jiwer): call the .venv_ml interpreter directly. Do NOT use
`uv run --python .venv_ml` — uv ignores .venv_ml's site-packages and instead
syncs the base .venv (which has no torch), so the run fails with ModuleNotFound.
    .venv_ml/bin/python ml_vision/scripts/analyze_errors.py --frozen
    .venv_ml/bin/python ml_vision/scripts/analyze_errors.py --page page_0550_human
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from html import escape
from pathlib import Path

import jiwer

REPO = Path(__file__).resolve().parent.parent.parent
FROZEN_DIR = REPO / "data/frozen_test_set"
LINES_DIR = REPO / "data/lines"
PRED_BASE = REPO / "data/predictions"
REPORTS = REPO / "reports"

WORST_N = 25  # rows shown in the HTML contact sheet

# Armenian punctuation / abbreviation marks (verjaket, abbreviation mark, mijaket…).
ABBREV_MARKS = set("։՟·՞՛՚՝")
# Heuristic: 1–3 Armenian letters immediately before a period read as a letter-numeral
# abbreviation (e.g. 'գկ.', 'աձ.'). Armenian has no distinct numeral codepoints, so this
# is necessarily a heuristic, not an exact classifier.
NUMERAL_RE = re.compile(r"[0-9Ա-Ֆա-ֆ]{1,3}\.")


def armenian_frac(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    arm = [c for c in letters if "԰" <= c <= "֏"]
    return len(arm) / len(letters)


def load_predictions(model_tag: str, page_key: str) -> dict[str, dict]:
    pred_path = PRED_BASE / model_tag / page_key / "predictions.json"
    if not pred_path.exists():
        raise SystemExit(
            f"No predictions at {pred_path.relative_to(REPO)}.\n"
            f"Run predict_lines.py first, e.g.:\n"
            f"  .venv_ml/bin/python ml_vision/scripts/predict_lines.py "
            f"{'--frozen' if page_key == 'frozen_test_set' else '--page ' + page_key}"
        )
    return json.loads(pred_path.read_text(encoding="utf-8"))["lines"]


def gather_frozen(model_tag: str) -> tuple[list[dict], dict]:
    preds = load_predictions(model_tag, "frozen_test_set")
    manifest = json.loads((FROZEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    src_map = {k: v for k, v in manifest["lines"].items()}  # line_NNN -> page_XXXX/line_NNN
    rows: list[dict] = []
    for line_id, pred in preds.items():
        ref = (FROZEN_DIR / f"{line_id}.txt").read_text(encoding="utf-8").strip()
        if not ref:
            continue  # section markers excluded from CER, same as training
        source = src_map.get(line_id, "?/?").split("/")[0]
        rows.append(
            {
                "id": line_id,
                "source_page": source,
                "column": "",
                "ref": ref,
                "pred_greedy": pred["pred_greedy"],
                "pred_beam": pred["pred_beam"],
                "png": FROZEN_DIR / f"{line_id}.png",
            }
        )
    return rows, {"target": "frozen_test_set"}


def gather_page(model_tag: str, page_id: str) -> tuple[list[dict], dict]:
    preds = load_predictions(model_tag, page_id)
    page_dir = LINES_DIR / page_id
    rows: list[dict] = []
    for line_id, pred in preds.items():  # id = "column_Y/line_NNN"
        col = int(line_id.split("/")[0].split("_")[1])
        ref = (page_dir / f"{line_id}.txt").read_text(encoding="utf-8").strip() if (
            page_dir / f"{line_id}.txt"
        ).exists() else ""
        if not ref:
            continue
        rows.append(
            {
                "id": line_id,
                "source_page": page_id,
                "column": col,
                "ref": ref,
                "pred_greedy": pred["pred_greedy"],
                "pred_beam": pred["pred_beam"],
                "png": page_dir / f"{line_id}.png",
            }
        )
    return rows, {"target": page_id}


def score(rows: list[dict]) -> None:
    """Add cer (beam), cer_greedy, ref_len, S/D/I, and notation flags to each row."""
    for r in rows:
        ref, beam, greedy = r["ref"], r["pred_beam"], r["pred_greedy"]
        out = jiwer.process_characters(ref, beam)
        r["cer"] = out.cer
        r["cer_greedy"] = jiwer.cer(ref, greedy)
        r["ref_len"] = len(ref)
        r["n_sub"] = out.substitutions
        r["n_del"] = out.deletions
        r["n_ins"] = out.insertions
        r["has_numeral"] = bool(NUMERAL_RE.search(ref))
        r["has_abbrev_mark"] = any(c in ABBREV_MARKS for c in ref)


def overall_cer(rows: list[dict], key: str) -> float:
    """Corpus CER (char-weighted, like jiwer over the whole list), not mean-of-means."""
    refs = [r["ref"] for r in rows]
    hyps = [r["pred_beam"] if key == "beam" else r["pred_greedy"] for r in rows]
    return jiwer.cer(refs, hyps)


def length_bins(rows: list[dict]) -> list[tuple[str, int, float]]:
    bins = [(0, 10), (11, 20), (21, 30), (31, 10**9)]
    out: list[tuple[str, int, float]] = []
    for lo, hi in bins:
        grp = [r for r in rows if lo <= r["ref_len"] <= hi]
        label = f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"
        if grp:
            mean = sum(r["cer"] for r in grp) / len(grp)
            out.append((label, len(grp), mean))
    return out


def group_mean(rows: list[dict], keyfn) -> list[tuple[str, int, float]]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(str(keyfn(r)), []).append(r)
    res = [(k, len(g), sum(x["cer"] for x in g) / len(g)) for k, g in groups.items()]
    return sorted(res, key=lambda t: -t[2])


def write_csv(rows: list[dict], path: Path) -> None:
    cols = [
        "id", "source_page", "column", "cer", "cer_greedy", "ref_len",
        "n_sub", "n_del", "n_ins", "has_numeral", "has_abbrev_mark",
        "ref", "pred_greedy", "pred_beam",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def write_html(rows: list[dict], path: Path, title: str, aggregates: dict) -> None:
    def img_src(png: Path) -> str:
        # reports/ -> repo-relative path the browser can load when the file is opened locally.
        return "../" + png.relative_to(REPO).as_posix()

    def agg_table(title: str, triples: list[tuple[str, int, float]]) -> str:
        body = "".join(
            f"<tr><td>{escape(k)}</td><td>{n}</td><td>{m:.4f} ({m*100:.1f}%)</td></tr>"
            for k, n, m in triples
        )
        return (
            f"<h3>{escape(title)}</h3>"
            f"<table class=agg><tr><th>group</th><th>n</th><th>mean CER</th></tr>{body}</table>"
        )

    worst = rows[:WORST_N]
    cards = []
    for r in worst:
        cards.append(
            f"<div class=card>"
            f"<img src='{escape(img_src(r['png']))}' />"
            f"<div class=meta>{escape(r['id'])} · {escape(str(r['source_page']))} · "
            f"CER {r['cer']:.3f} (greedy {r['cer_greedy']:.3f}) · len {r['ref_len']} · "
            f"S{r['n_sub']} D{r['n_del']} I{r['n_ins']}"
            f"{' · numeral' if r['has_numeral'] else ''}"
            f"{' · mark' if r['has_abbrev_mark'] else ''}</div>"
            f"<div class=ref><b>REF </b>{escape(r['ref'])}</div>"
            f"<div class=pred><b>BEAM</b> {escape(r['pred_beam'])}</div>"
            f"<div class=pred><b>GRDY</b> {escape(r['pred_greedy'])}</div>"
            f"</div>"
        )

    summary = (
        f"<p><b>Lines:</b> {aggregates['n']} · "
        f"<b>overall CER (beam):</b> {aggregates['cer_beam']:.4f} ({aggregates['cer_beam']*100:.1f}%) · "
        f"<b>overall CER (greedy):</b> {aggregates['cer_greedy']:.4f} ({aggregates['cer_greedy']*100:.1f}%)</p>"
        f"<p class=sanity><b>Degeneracy sanity:</b> mean Armenian-letter fraction "
        f"{aggregates['arm_frac']:.2f} · empty preds {aggregates['empty']}/{aggregates['n']} · "
        f"distinct preds {aggregates['distinct']}/{aggregates['n']}</p>"
    )

    aggs_html = (
        agg_table("Mean CER by source page", aggregates["by_page"])
        + agg_table("Mean CER by ref-length bin", aggregates["by_len"])
        + agg_table("Mean CER by notation flag", aggregates["by_flag"])
    )

    html = f"""<!doctype html><meta charset=utf-8>
<title>{escape(title)}</title>
<style>
 body {{ font-family: -apple-system, system-ui, sans-serif; background:#15161a; color:#e8e8ec; margin:1.5rem; }}
 h1 {{ font-size:1.2rem; }} h3 {{ margin-top:1.4rem; }}
 .sanity {{ color:#9aa0ac; }}
 table.agg {{ border-collapse:collapse; margin:.3rem 0 1rem; }}
 table.agg td, table.agg th {{ border:1px solid #3a3d46; padding:.25rem .6rem; text-align:left; font-size:.85rem; }}
 .card {{ background:#2a2c33; border:1px solid #3a3d46; border-radius:8px; padding:.6rem; margin:.5rem 0; }}
 .card img {{ background:#f4f4f4; max-width:100%; display:block; padding:4px; border-radius:4px; }}
 .meta {{ color:#9aa0ac; font-size:.8rem; margin:.3rem 0; }}
 .ref {{ font-size:1.2rem; }} .pred {{ font-size:1.1rem; color:#bfe3ff; }}
 .ref b, .pred b {{ color:#9aa0ac; font-size:.7rem; }}
</style>
<h1>{escape(title)}</h1>
{summary}
{aggs_html}
<h3>Worst {len(worst)} lines (sorted CER-desc)</h3>
{''.join(cards)}
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--frozen", action="store_true")
    g.add_argument("--page", type=str)
    parser.add_argument("--model-tag", default="scale_500")
    args = parser.parse_args()

    # Non-default tags (e.g. an LLM-corrected scale_500_llm_* tag) get the tag in the
    # report filename so re-scoring a corrected pass doesn't clobber the baseline
    # report. The default "scale_500" keeps the original stems for back-compat.
    tag_suffix = "" if args.model_tag == "scale_500" else f"_{args.model_tag}"

    if args.frozen:
        rows, meta = gather_frozen(args.model_tag)
        stem = f"phase4_error_analysis_frozen{tag_suffix}"
        title = f"Phase 4 error analysis — frozen test set ({args.model_tag})"
    else:
        rows, meta = gather_page(args.model_tag, args.page)
        stem = f"phase4_newpage_{args.page}{tag_suffix}"
        title = f"Phase 4 error analysis — {args.page} ({args.model_tag})"

    if not rows:
        raise SystemExit("No non-empty GT lines matched the predictions.")

    score(rows)
    rows.sort(key=lambda r: -r["cer"])

    by_page = group_mean(rows, lambda r: r["source_page"])
    by_len = length_bins(rows)
    flag_groups = [
        ("has_numeral", [r for r in rows if r["has_numeral"]]),
        ("no_numeral", [r for r in rows if not r["has_numeral"]]),
        ("has_abbrev_mark", [r for r in rows if r["has_abbrev_mark"]]),
        ("no_abbrev_mark", [r for r in rows if not r["has_abbrev_mark"]]),
    ]
    by_flag = [
        (name, len(g), sum(r["cer"] for r in g) / len(g)) for name, g in flag_groups if g
    ]

    preds_beam = [r["pred_beam"] for r in rows]
    aggregates = {
        "n": len(rows),
        "cer_beam": overall_cer(rows, "beam"),
        "cer_greedy": overall_cer(rows, "greedy"),
        "arm_frac": sum(armenian_frac(p) for p in preds_beam) / len(preds_beam),
        "empty": sum(1 for p in preds_beam if not p.strip()),
        "distinct": len(set(preds_beam)),
        "by_page": by_page,
        "by_len": by_len,
        "by_flag": by_flag,
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    write_csv(rows, REPORTS / f"{stem}.csv")
    json_rows = [{k: v for k, v in r.items() if k != "png"} for r in rows]
    (REPORTS / f"{stem}.json").write_text(
        json.dumps({"aggregates": {k: v for k, v in aggregates.items()},
                    "rows": json_rows}, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    write_html(rows, REPORTS / f"{stem}.html", title, aggregates)

    # Console summary
    print(f"\n{title}")
    print(f"  lines: {aggregates['n']}")
    print(f"  overall CER  beam {aggregates['cer_beam']:.4f} ({aggregates['cer_beam']*100:.1f}%) | "
          f"greedy {aggregates['cer_greedy']:.4f} ({aggregates['cer_greedy']*100:.1f}%)")
    print(f"  Armenian frac {aggregates['arm_frac']:.2f} · empty {aggregates['empty']}/{aggregates['n']} · "
          f"distinct {aggregates['distinct']}/{aggregates['n']}")
    print("  Mean CER by source page:")
    for k, n, m in by_page:
        print(f"    {k:<14} n={n:<4} {m*100:5.1f}%")
    print("  Mean CER by ref-length bin:")
    for k, n, m in by_len:
        print(f"    len {k:<8} n={n:<4} {m*100:5.1f}%")
    print("  Mean CER by notation flag:")
    for k, n, m in by_flag:
        print(f"    {k:<16} n={n:<4} {m*100:5.1f}%")
    print(f"\n  wrote reports/{stem}.{{csv,json,html}}")


if __name__ == "__main__":
    main()
