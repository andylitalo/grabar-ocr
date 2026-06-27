"""
Phase 5b — Gemini thinking-budget × model sweep (see docs/phase_5b_*.md).

Drives the EXACT production correction (llm_correct.correct_page → CER vs GT) and
translation (pipeline.translate.translate_page) paths, but monkeypatches
llm_correct.call_gemini with a thinking_budget-aware variant (with an HTTP timeout
so a stuck connection can't hang the run) so we can measure how latency / cost /
quality move as we cap the model's reasoning. Production code is untouched.

Results are written to reports/phase5b_budget_sweep.csv **incrementally** (one row
per cell, flushed) so a crash/kill never loses completed cells; re-running resumes
(cells already in the CSV are skipped). Run unbuffered for live progress:

    PYTHONUNBUFFERED=1 .venv/bin/python experiments/gemini_budget_sweep.py
    PYTHONUNBUFFERED=1 .venv/bin/python experiments/gemini_budget_sweep.py --smoke
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ml_vision/scripts"))
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

import llm_correct as lc
from pipeline import translate as tr

lc.MODELS["gemini-3.5-flash"] = ("gemini", "gemini-3.5-flash", "g35flash")
lc.PRICE_PER_MTOK["gemini-3.5-flash"] = (0.30, 2.50)  # ESTIMATE — verify before quoting

CORR_PAGES = ["page_0400_human", "page_0451_human", "page_0499_human"]
TRANS_PAGES = ["page_0400_human", "page_0474_auto"]
BASELINE_TAG = "tesseract"
PRO_BUDGETS = [None, 2048, 512, 128]
FLASH_BUDGETS = [None, 512, 0]
GRID = {"gemini-3.1-pro": PRO_BUDGETS, "gemini-3.5-flash": FLASH_BUDGETS}
HTTP_TIMEOUT_MS = 180_000  # bound true hangs; still > a legit ~90s dynamic-thinking call

_CAP: dict = {}


def _patched_call_gemini(model: str, system: str, user: str):
    from google import genai
    from google.genai import types as gt

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=gt.HttpOptions(timeout=HTTP_TIMEOUT_MS),
    )
    cfg_kw = dict(system_instruction=system, max_output_tokens=lc.MAX_TOKENS)
    budget = _CAP.get("budget")
    if budget is not None:
        cfg_kw["thinking_config"] = gt.ThinkingConfig(thinking_budget=budget)

    def _go():
        return client.models.generate_content(
            model=model, contents=user, config=gt.GenerateContentConfig(**cfg_kw)
        )

    t0 = time.perf_counter()
    resp = lc._retry(_go, label=model)
    _CAP["latency"] = time.perf_counter() - t0
    um = resp.usage_metadata
    _CAP["thoughts"] = getattr(um, "thoughts_token_count", None) or 0
    _CAP["in_tok"] = um.prompt_token_count or 0
    _CAP["out_tok"] = um.candidates_token_count or 0
    return (resp.text or "").strip(), _CAP["in_tok"], _CAP["out_tok"]


lc.CALL_FN["gemini"] = _patched_call_gemini


def _cost(model: str, in_tok: int, out_tok: int) -> float:
    ip, op = lc.PRICE_PER_MTOK[model]
    return in_tok / 1e6 * ip + out_tok / 1e6 * op


def _blabel(budget) -> str:
    return "dynamic" if budget is None else str(budget)


def correction_cells(models):
    for model in models:
        for budget in GRID[model]:
            for page in CORR_PAGES:
                yield model, budget, page


def translation_cells(models):
    for page in TRANS_PAGES:
        for model in models:
            for budget in GRID[model]:
                yield model, budget, page


def do_correction(model, budget, page) -> dict:
    _CAP.clear(); _CAP["budget"] = budget
    res = lc.correct_page(page, model, "minimal-edit", BASELINE_TAG)
    return {
        "stage": "correct", "model": model, "budget": _blabel(budget), "page": page,
        "cer_baseline": round(res["cer_baseline"], 4),
        "cer_corrected": round(res["cer_corrected"], 4),
        "abs_reduction": round(res["abs_reduction"], 4),
        "made_worse": res["made_worse"], "n": res["n"],
        "latency_s": round(_CAP.get("latency", 0), 1), "thoughts": _CAP.get("thoughts", 0),
        "out_tok": _CAP.get("out_tok", 0),
        "cost": round(_cost(model, _CAP.get("in_tok", 0), _CAP.get("out_tok", 0)), 5),
    }


def do_translation(model, budget, page, outdir: Path) -> dict:
    import json
    pj = REPO / "data/predictions" / BASELINE_TAG / page / "predictions.json"
    lines = json.loads(pj.read_text())["lines"]
    page_text = "\n".join(v.get("pred_beam", "") for v in lines.values() if v.get("pred_beam"))
    src_lines = sum(1 for l in page_text.splitlines() if l.strip())
    _CAP.clear(); _CAP["budget"] = budget
    res = tr.translate_page(page_text, model)
    out_lines = sum(1 for l in res["text"].splitlines() if l.strip())
    (outdir / f"{page}__{model}__b{_blabel(budget)}.txt").write_text(res["text"] + "\n", encoding="utf-8")
    return {
        "stage": "translate", "model": model, "budget": _blabel(budget), "page": page,
        "src_lines": src_lines, "out_lines": out_lines,
        "latency_s": round(_CAP.get("latency", 0), 1), "thoughts": _CAP.get("thoughts", 0),
        "out_tok": res["out_tokens"], "cost": round(res["cost"], 5),
    }


COLS = ["stage", "model", "budget", "page", "cer_baseline", "cer_corrected",
        "abs_reduction", "made_worse", "src_lines", "out_lines", "n",
        "latency_s", "thoughts", "out_tok", "cost", "error"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--stage", choices=["correct", "translate", "both"], default="both")
    args = ap.parse_args()

    models = ["gemini-3.1-pro", "gemini-3.5-flash"]
    global CORR_PAGES, TRANS_PAGES, GRID
    if args.smoke:
        CORR_PAGES = ["page_0400_human"]; TRANS_PAGES = ["page_0474_auto"]
        GRID = {"gemini-3.1-pro": [512], "gemini-3.5-flash": [512]}

    reports = REPO / "reports"; reports.mkdir(exist_ok=True)
    tdir = reports / "phase5b_translations"; tdir.mkdir(exist_ok=True)
    csv_path = reports / "phase5b_budget_sweep.csv"

    # Resume: skip (stage,model,budget,page) cells already in the CSV.
    done: set[tuple] = set()
    if csv_path.exists():
        with csv_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                done.add((r["stage"], r["model"], r["budget"], r["page"]))
    f = csv_path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=COLS)
    if not done:
        w.writeheader(); f.flush()

    def emit(row: dict):
        w.writerow({c: row.get(c, "") for c in COLS}); f.flush()

    plan = []
    if args.stage in ("correct", "both"):
        plan += [("correct", m, b, p) for (m, b, p) in correction_cells(models)]
    if args.stage in ("translate", "both"):
        plan += [("translate", m, b, p) for (m, b, p) in translation_cells(models)]

    for stage, model, budget, page in plan:
        key = (stage, model, _blabel(budget), page)
        if key in done:
            print(f"  SKIP {stage} {model} b={_blabel(budget)} {page} (cached)"); continue
        try:
            row = do_correction(model, budget, page) if stage == "correct" \
                else do_translation(model, budget, page, tdir)
        except Exception as e:
            print(f"  ERROR {stage} {model} b={_blabel(budget)} {page}: {str(e)[:100]}")
            emit({"stage": stage, "model": model, "budget": _blabel(budget),
                  "page": page, "error": str(e)[:160]})
            continue
        emit(row)
        if stage == "correct":
            print(f"  CORR {model:17s} b={_blabel(budget):7s} {page:17s} "
                  f"CER {row['cer_baseline']:.3f}->{row['cer_corrected']:.3f} "
                  f"worse={row['made_worse']:2d} {row['latency_s']:5.1f}s think={row['thoughts']}")
        else:
            print(f"  TRANS {model:17s} b={_blabel(budget):7s} {page:17s} "
                  f"lines {row['src_lines']}->{row['out_lines']} {row['latency_s']:5.1f}s "
                  f"think={row['thoughts']} ${row['cost']:.4f}")
    f.close()
    print(f"\nDone. CSV: {csv_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
