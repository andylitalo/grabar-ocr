"""
Production OCR -> LLM digitizer for a page with NO ground truth.

llm_correct.py is the *evaluation* harness: it needs hand transcriptions to score
corrected CER, so it only runs on human-labeled pages. This script is the
*production* path — it takes the baseline TrOCR predictions for any page (e.g. an
auto-sliced page_XXXX_auto that nobody has transcribed), runs the same whole-page
LLM correction, and emits the final digitized Grabar text. No refs, no scoring.

It reuses llm_correct's tested primitives unchanged (prompts, provider clients,
minimal-edit/rewrite parsing + application) so correction behaviour is identical to
the evaluated path; only the scoring is dropped. Corrected predictions are written
in predict_lines.py format under the same scale_500_llm_<model>_<mode> tag (so the
Review UI and analyze_errors can read them), plus a joined digitized.txt.

Run (BASE env — SDKs, no torch): call the .venv interpreter directly.
    .venv/bin/python ml_vision/scripts/digitize_page.py --page page_0487_auto
    .venv/bin/python ml_vision/scripts/digitize_page.py --page page_0487_auto \
        --model claude-opus-4-8 --mode rewrite
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import llm_correct as lc  # tested primitives: prompts, clients, parse/apply

REPO = Path(__file__).resolve().parent.parent.parent
PRED_BASE = REPO / "data/predictions"


def load_baseline_rows(baseline_tag: str, page: str) -> list[dict]:
    """Rows in page reading order from a baseline predictions.json (beam text).

    predict_lines.py writes `lines` in collect order (column_1 sorted, then
    column_2, ...), so dict insertion order already is reading order.
    """
    pred_path = PRED_BASE / baseline_tag / page / "predictions.json"
    if not pred_path.exists():
        raise SystemExit(
            f"No baseline predictions at {pred_path.relative_to(REPO)}.\n"
            f"Run predict_lines.py first:  .venv_ml/bin/python "
            f"ml_vision/scripts/predict_lines.py --page {page}"
        )
    data = json.loads(pred_path.read_text(encoding="utf-8"))["lines"]
    rows = []
    for line_id, p in data.items():  # id = "column_Y/line_NNN"
        rows.append(
            {
                "id": line_id,
                "column": p.get("column"),
                "pred_beam": p.get("pred_beam", ""),
                # Carry the pre-OCR non-character marker (+ its features) through so
                # such lines are excluded from the LLM prompt and digitized.txt yet
                # retained in the written manifest for auditability.
                "non_character": bool(p.get("non_character")),
                "glyph_count": p.get("glyph_count"),
                "ink_ratio": p.get("ink_ratio"),
            }
        )
    return rows


def digitize(page: str, cli_model: str, mode: str, baseline_tag: str) -> dict:
    provider, api_model, short = lc.MODELS[cli_model]
    rows = load_baseline_rows(baseline_tag, page)
    if not rows:
        raise SystemExit(f"No baseline rows for {page} (tag {baseline_tag}).")

    # Non-character lines (pre-OCR ornamental dividers / specks) are never shown to
    # the LLM. They carry no real text, so the model never sees them and never
    # numbers over them; the block + parse run over the text rows only.
    text_rows = [r for r in rows if not r["non_character"]]
    for r in rows:
        if r["non_character"]:
            r["corrected"] = ""  # pred_beam is already "" — kept empty in outputs
            r["applied"] = False
    if not text_rows:
        raise SystemExit(f"All {len(rows)} lines of {page} were non-character; nothing to digitize.")

    n = len(text_rows)
    n_nonchar = len(rows) - n
    system = lc.REWRITE_SYSTEM if mode == "rewrite" else lc.MINIMAL_EDIT_SYSTEM
    user = (
        f"Correct the OCR of these {n} lines of one Grabar page. "
        f"Return your answer in the required format.\n\n{lc.build_block(text_rows)}"
    )

    print(f"Digitizing {page}: {n} text lines ({n_nonchar} non-character skipped) "
          f"via {cli_model} ({api_model}) [{mode}]")
    reply, in_tok, out_tok = lc.CALL_FN[provider](api_model, system, user)

    if mode == "rewrite":
        corr_map, parse_ok = lc.parse_rewrite(reply, n)
        for i, r in enumerate(text_rows, start=1):
            r["corrected"] = corr_map.get(i, r["pred_beam"])
            r["applied"] = i in corr_map
    else:
        edit_map, parse_ok = lc.parse_minimal_edit(reply, n)
        for i, r in enumerate(text_rows, start=1):
            new_text, _ = lc.apply_minimal_edits(r["pred_beam"], edit_map.get(i, {}))
            r["corrected"] = new_text
            r["applied"] = new_text != r["pred_beam"]

    n_changed = sum(1 for r in text_rows if r["corrected"] != r["pred_beam"])
    in_price, out_price = lc.PRICE_PER_MTOK[cli_model]
    cost = in_tok / 1e6 * in_price + out_tok / 1e6 * out_price

    return {
        "page": page, "cli_model": cli_model, "api_model": api_model,
        "modelshort": short, "provider": provider, "mode": mode,
        "baseline_tag": baseline_tag, "n": n, "n_nonchar": n_nonchar, "rows": rows,
        "parse_ok": parse_ok, "n_changed": n_changed,
        "in_tokens": in_tok, "out_tokens": out_tok, "cost_page": cost,
    }


def write_outputs(res: dict) -> tuple[Path, Path]:
    """Corrected predictions (predict_lines.py format) + joined digitized.txt."""
    tag = f"{res['baseline_tag']}_llm_{res['modelshort']}_{res['mode']}"
    out_dir = PRED_BASE / tag / res["page"]
    out_dir.mkdir(parents=True, exist_ok=True)

    # Manifest retains EVERY line (non-character ones keep their marker + features)
    # so line positions stay auditable; digitized.txt below contains text lines only.
    lines = {}
    for r in res["rows"]:
        entry = {"column": r["column"], "pred_greedy": r["corrected"], "pred_beam": r["corrected"]}
        if r.get("non_character"):
            entry["non_character"] = True
            entry["glyph_count"] = r.get("glyph_count")
            entry["ink_ratio"] = r.get("ink_ratio")
        lines[r["id"]] = entry
    manifest = {
        "model_tag": tag, "corrected_from": res["baseline_tag"],
        "cli_model": res["cli_model"], "api_model": res["api_model"],
        "provider": res["provider"], "mode": res["mode"], "target": res["page"],
        "no_reference": True,  # production digitize: no gold, no CER scored
        "n_non_character": res.get("n_nonchar", 0),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "usage": {"input_tokens": res["in_tokens"], "output_tokens": res["out_tokens"]},
        "lines": lines,
    }
    pred_path = out_dir / "predictions.json"
    pred_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    txt_path = out_dir / "digitized.txt"
    text_lines = [r["corrected"] for r in res["rows"] if not r.get("non_character")]
    txt_path.write_text("\n".join(text_lines) + "\n", encoding="utf-8")
    return pred_path, txt_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", required=True, help="page id, e.g. page_0487_auto")
    ap.add_argument("--model", default="gemini-3.1-pro", choices=list(lc.MODELS))
    ap.add_argument("--mode", default="minimal-edit", choices=["minimal-edit", "rewrite"])
    ap.add_argument("--baseline-tag", default="scale_500")
    args = ap.parse_args()

    res = digitize(args.page, args.model, args.mode, args.baseline_tag)
    pred_path, txt_path = write_outputs(res)

    print(f"\n  {res['page']} · {res['cli_model']} [{res['mode']}]  "
          f"(n={res['n']} text · {res['n_nonchar']} non-character skipped)")
    print(f"  lines changed by correction: {res['n_changed']}/{res['n']}")
    print(f"  parse_ok {res['parse_ok']} · cost ${res['cost_page']:.4f}/page "
          f"(in {res['in_tokens']} / out {res['out_tokens']} tok)")
    print(f"  wrote {pred_path.relative_to(REPO)}")
    print(f"  wrote {txt_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
