"""
Phase 5 — LLM post-correction of OCR output.

Takes the baseline TrOCR predictions for a *complete, contiguous* page
(predict_lines.py output under data/predictions/<baseline-tag>/), concatenates
the predicted lines into one numbered block so a frontier LLM sees the whole-page
semantic context, and asks the model to fix the residual confusable-letter
substitutions and dropped spaces — WITHOUT paraphrasing, translating, or altering
notation. It then scores corrected CER vs baseline, an over-correction rate, and
per-page cost for each model.

This NEVER runs the OCR model; it only reads what predict_lines.py wrote and
calls the Anthropic / OpenAI / Gemini APIs. It reuses analyze_errors.py for
scoring (load_predictions, gather_page, score, overall_cer, armenian_frac) and the
vlm_benchmark.py per-provider client construction pattern.

Two correction modes:
  rewrite       (default) — model returns the same N numbered lines, corrected.
                Realignment guardrail: mismatched line counts/numbers fall back to
                baseline (never silently dropped/shifted) and set parse_ok=False.
  minimal-edit  — model returns structured JSON of tiny deterministic substring
                replacements per line; we apply them as string replaces on the
                baseline. Lines with no entry stay byte-identical to baseline,
                structurally capping over-correction and paraphrase risk.

Corrected predictions are written back in the predict_lines.py format under a new
tag (scale_500_llm_<modelshort>_<mode>) so analyze_errors.py can re-score them
directly. Per-run reports go to reports/phase5_correction_*; a rolling
reports/phase5_correction_summary.{md,csv,json} tabulates every run.

Run (BASE env — SDKs + jiwer, no torch): call the .venv interpreter directly.
    .venv/bin/python ml_vision/scripts/llm_correct.py --page page_0400_human --model claude-opus-4-8
    .venv/bin/python ml_vision/scripts/llm_correct.py --page page_0499_human --model gpt-5.5 --mode minimal-edit
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import jiwer
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from analyze_errors import (  # noqa: E402  (reuse the Phase-4 scoring helpers)
    armenian_frac,
    gather_page,
    overall_cer,
    score,
)

REPO = Path(__file__).resolve().parent.parent.parent
PRED_BASE = REPO / "data/predictions"
REPORTS = REPO / "reports"
WORST_N = 25  # cards shown in the per-run HTML contact sheet
# Output budget. Generous because adaptive/thinking models spend tokens reasoning
# before emitting the numbered answer; at 8000 a ~90-line page truncated mid-answer
# (parse_ok False → full baseline fallback). 16000 stays within the non-streaming
# SDK timeout guard while leaving room to think + return every line.
MAX_TOKENS = 16000

load_dotenv(REPO / ".env")

# ── Model dispatch ──────────────────────────────────────────────────────────────
# Canonical CLI id -> (provider, exact API model string, short tag for filenames).
# Anthropic ids confirmed via the claude-api skill (2026-05-26). gpt-5.5 confirmed
# present in the OpenAI models list. Gemini has no bare "gemini-3.1-pro" — the
# served model is "gemini-3.1-pro-preview", so the CLI alias routes to it.
MODELS: dict[str, tuple[str, str, str]] = {
    "claude-opus-4-8":   ("anthropic", "claude-opus-4-8",        "opus"),
    "claude-sonnet-4-6": ("anthropic", "claude-sonnet-4-6",      "sonnet"),
    "gpt-5.5":           ("openai",    "gpt-5.5",                "gpt55"),
    "gemini-3.1-pro":    ("gemini",    "gemini-3.1-pro-preview", "gemini"),
}

# Per-model token pricing, ($ per 1M input, $ per 1M output).
# Anthropic confirmed from the claude-api skill. OpenAI/Gemini are ESTIMATES —
# verify against the provider pricing pages and update before quoting cost.
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8":   (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "gpt-5.5":           (1.25, 10.00),   # ESTIMATE — update at build time
    "gemini-3.1-pro":    (2.00, 12.00),   # ESTIMATE — update at build time
}

REWRITE_SYSTEM = (
    "You correct OCR of Classical Armenian (Grabar) printed in Bolorgir script. "
    "You are given the machine-transcribed lines of one complete, contiguous page, "
    "numbered in reading order. Use the meaning across the lines to fix OCR errors — "
    "almost always single confusable-letter substitutions (e.g. Խ↔ձ, լ↔յ/ղ, տ↔ս, "
    "փ↔կ) and occasional dropped or spurious spaces.\n\n"
    "STRICT RULES:\n"
    "- Do NOT paraphrase, translate, modernize spelling, reorder, or add/remove "
    "content. Change only characters that are OCR mistakes.\n"
    "- Fix ONLY a letter INSIDE a multi-letter word that is clearly a misread of a "
    "look-alike letter. That is the only kind of edit allowed.\n"
    "- Do NOT touch punctuation or spacing in any way: never add, delete, or swap a "
    "period/comma/`։`/`՟`/`·`/`՞`/`՛`/`՚`/`՝`/hyphen, and never add or remove a space — "
    "including around abbreviations and citations (leave `վ 26`, `ահ,`, `անդր` exactly "
    "as given).\n"
    "- Do NOT change digits, letter-numerals, or abbreviations — especially short tokens "
    "that are a letter or two followed by a period (e.g. `ժ.`, `վ.`, `ԺԱ.`, `դկ.`). Leave "
    "their letters AND their case untouched; never 'fix' `ժ.`→`Ժ.`.\n"
    "- Preserve the original letter case of every word exactly. Do NOT capitalize a "
    "lowercase word (e.g. a proper noun) or lowercase a capital.\n"
    "- Preserve all notation exactly: Armenian punctuation and abbreviation marks "
    "(։ ՟ · ՞ ՛ ՚ ՝), letter-numerals, and trailing hyphens.\n"
    "- When unsure whether something is an OCR error, LEAVE IT UNCHANGED. Missing a fix "
    "is far better than altering a line that was already correct.\n"
    "- If a line is already correct, return it unchanged.\n"
    "- Return EXACTLY the same number of lines, with the SAME line numbers, in the "
    "same order, formatted as `<number>\\t<corrected text>` — one per line, and "
    "nothing else (no commentary, no code fences)."
)

MINIMAL_EDIT_SYSTEM = (
    "You correct OCR of Classical Armenian (Grabar) printed in Bolorgir script. "
    "You are given the machine-transcribed lines of one complete, contiguous page, "
    "numbered in reading order. Use the meaning across the lines to find OCR errors "
    "— almost always single confusable-letter substitutions (e.g. Խ↔ձ, լ↔յ/ղ, տ↔ս, "
    "փ↔կ) and occasional dropped or spurious spaces.\n\n"
    "Return ONLY a JSON object (no commentary, no code fences) mapping the line "
    "number (as a string) to an object of replacements for that line: each key is a "
    "short substring AS IT CURRENTLY APPEARS in that line (1–4 characters, optionally "
    "including a letter or two on each side to make the match unambiguous) and each "
    "value is the corrected substring. Example: {\"12\": {\"անէն\": \"ամեն\"}}.\n\n"
    "STRICT RULES:\n"
    "- Only include lines that need a fix. Omit lines that are already correct, and when "
    "unsure LEAVE THE LINE OUT — missing a fix is far better than altering a correct line.\n"
    "- Each replacement may ONLY swap a letter INSIDE a multi-letter word for the look-alike "
    "letter the OCR misread. Both key and value must be Armenian letters of the SAME case and "
    "SAME length region — a pure in-word letter fix.\n"
    "- Never propose an edit that adds, deletes, or changes punctuation or spacing "
    "(period/comma/`։`/`՟`/`·`/`՞`/`՛`/`՚`/`՝`/hyphen/space), a digit, a letter-numeral, or a "
    "short abbreviation token like `ժ.`/`վ.`/`ԺԱ.`/`դկ.` — leave `վ 26`, `ահ,`, `անդր`, `ժ.` "
    "exactly as given. Do NOT change any letter's case (no `ժ.`→`Ժ.`, no proper-noun caps).\n"
    "- Each key MUST occur verbatim in that line's text, and the edit must be a pure OCR fix "
    "— never a paraphrase, translation, or modernization."
)


# ── Provider clients (text-only; mirrors vlm_benchmark.py construction) ─────────

def _retry(fn, *, label: str, attempts: int = 3):
    """Call fn() with simple backoff on transient (rate/5xx/overloaded) errors."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — provider exception types vary
            msg = str(e)
            # insufficient_quota is a permanent 429 (no billing) — don't retry it.
            transient = "insufficient_quota" not in msg and any(
                c in msg for c in ("429", "500", "502", "503", "529",
                                   "overloaded", "UNAVAILABLE", "rate"))
            if attempt < attempts - 1 and transient:
                wait = (attempt + 1) * 10
                print(f"  RETRY {label} in {wait}s ({msg[:90]})")
                time.sleep(wait)
            else:
                raise


def call_anthropic(model: str, system: str, user: str) -> tuple[str, int, int]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def _go():
        # Opus 4.8 / Sonnet 4.6: adaptive thinking, no sampling params (would 400).
        return client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
        )

    resp = _retry(_go, label=model)
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text, resp.usage.input_tokens, resp.usage.output_tokens


def call_openai(model: str, system: str, user: str) -> tuple[str, int, int]:
    from openai import OpenAI

    # Non-streaming reasoning requests can run long; cap the per-request wall clock
    # and disable the SDK's own retries (our _retry handles transient errors) so a
    # hang fails in minutes, not ~3×10min. reasoning_effort="low" keeps this
    # mechanical correction task fast and cheap (gpt-5 family reasons by default).
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=300.0, max_retries=0)

    def _go():
        return client.chat.completions.create(
            model=model,
            max_completion_tokens=MAX_TOKENS,
            reasoning_effort="low",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

    resp = _retry(_go, label=model)
    text = (resp.choices[0].message.content or "").strip()
    return text, resp.usage.prompt_tokens, resp.usage.completion_tokens


def call_gemini(model: str, system: str, user: str) -> tuple[str, int, int]:
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def _go():
        return client.models.generate_content(
            model=model,
            contents=user,
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=MAX_TOKENS,
            ),
        )

    resp = _retry(_go, label=model)
    text = (resp.text or "").strip()
    um = resp.usage_metadata
    return text, um.prompt_token_count or 0, (um.candidates_token_count or 0)


CALL_FN = {"anthropic": call_anthropic, "openai": call_openai, "gemini": call_gemini}


# ── Block build + reply parsing ─────────────────────────────────────────────────

def build_block(rows: list[dict]) -> str:
    """One numbered line per scored row (page order), `<n>\\t<pred_beam>`."""
    return "\n".join(f"{i}\t{r['pred_beam']}" for i, r in enumerate(rows, start=1))


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


_LINE_RE = re.compile(r"^\s*(\d+)[\.\):\t]?\s+(.*)$")


def parse_rewrite(reply: str, n: int) -> tuple[dict[int, str], bool]:
    """Map line_no -> corrected text. Returns (map, parse_ok). parse_ok is True
    only when the reply yields exactly lines 1..n once each."""
    out: dict[int, str] = {}
    for raw in _strip_fences(reply).splitlines():
        if not raw.strip():
            continue
        m = _LINE_RE.match(raw)
        if not m:
            continue
        ln = int(m.group(1))
        if 1 <= ln <= n and ln not in out:
            out[ln] = m.group(2).rstrip("\n")
    parse_ok = len(out) == n and all(i in out for i in range(1, n + 1))
    return out, parse_ok


def parse_minimal_edit(reply: str, n: int) -> tuple[dict[int, dict[str, str]], bool]:
    """Parse JSON {line_no_str: {find: replace}}. Returns (map, parse_ok)."""
    text = _strip_fences(reply)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}, False
    try:
        raw = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}, False
    out: dict[int, dict[str, str]] = {}
    for k, v in raw.items():
        try:
            ln = int(k)
        except (TypeError, ValueError):
            continue
        if 1 <= ln <= n and isinstance(v, dict):
            out[ln] = {str(a): str(b) for a, b in v.items()}
    return out, True


def apply_minimal_edits(
    baseline: str, edits: dict[str, str]
) -> tuple[str, list[str]]:
    """Apply each find->replace once. Return (text, rejected_keys) where a key is
    rejected (and skipped) if it doesn't occur in the current line text."""
    text = baseline
    rejected: list[str] = []
    for find, repl in edits.items():
        if find and find in text:
            text = text.replace(find, repl, 1)
        else:
            rejected.append(find)
    return text, rejected


# ── Correction driver ───────────────────────────────────────────────────────────

def correct_page(
    page: str, cli_model: str, mode: str, baseline_tag: str
) -> dict:
    provider, api_model, short = MODELS[cli_model]
    rows, _ = gather_page(baseline_tag, page)  # non-empty-ref lines, page order
    if not rows:
        raise SystemExit(f"No scored baseline rows for {page} (tag {baseline_tag}).")
    score(rows)  # adds baseline cer/cer_greedy/ref_len/... using pred_beam

    n = len(rows)
    system = REWRITE_SYSTEM if mode == "rewrite" else MINIMAL_EDIT_SYSTEM
    user = (
        f"Correct the OCR of these {n} lines of one Grabar page. "
        f"Return your answer in the required format.\n\n{build_block(rows)}"
    )

    print(f"Correcting {page}: {n} lines via {cli_model} ({api_model}) [{mode}]")
    reply, in_tok, out_tok = CALL_FN[provider](api_model, system, user)

    rejected_edits = 0
    if mode == "rewrite":
        corr_map, parse_ok = parse_rewrite(reply, n)
        for i, r in enumerate(rows, start=1):
            applied = i in corr_map
            r["corrected"] = corr_map[i] if applied else r["pred_beam"]
            r["applied"] = applied  # False => fell back to baseline for this line
    else:
        edit_map, parse_ok = parse_minimal_edit(reply, n)
        for i, r in enumerate(rows, start=1):
            edits = edit_map.get(i, {})
            new_text, rej = apply_minimal_edits(r["pred_beam"], edits)
            rejected_edits += len(rej)
            r["corrected"] = new_text
            r["applied"] = new_text != r["pred_beam"]

    # Per-line scoring: baseline cer is already r["cer"] (beam). Add corrected cer.
    for r in rows:
        r["cer_corrected"] = jiwer.cer(r["ref"], r["corrected"])

    refs = [r["ref"] for r in rows]
    cer_baseline = overall_cer(rows, "beam")  # corpus, char-weighted
    cer_corrected = jiwer.cer(refs, [r["corrected"] for r in rows])

    # Over-correction signals.
    made_worse = sum(1 for r in rows if r["cer_corrected"] > r["cer"] + 1e-9)
    was_correct = [r for r in rows if r["cer"] <= 1e-9]
    broke_correct = sum(1 for r in was_correct if r["cer_corrected"] > 1e-9)
    n_changed = sum(1 for r in rows if r["corrected"] != r["pred_beam"])

    # Paraphrase / hallucination guard (page-level).
    base_arm = sum(armenian_frac(r["pred_beam"]) for r in rows) / n
    corr_arm = sum(armenian_frac(r["corrected"]) for r in rows) / n
    ref_chars = sum(len(r["ref"]) for r in rows)
    corr_chars = sum(len(r["corrected"]) for r in rows)
    len_ratio = corr_chars / ref_chars if ref_chars else 0.0
    paraphrase_flag = (corr_arm < base_arm - 0.05) or abs(len_ratio - 1.0) > 0.15

    in_price, out_price = PRICE_PER_MTOK[cli_model]
    cost_page = in_tok / 1e6 * in_price + out_tok / 1e6 * out_price

    return {
        "page": page,
        "cli_model": cli_model,
        "api_model": api_model,
        "modelshort": short,
        "provider": provider,
        "mode": mode,
        "baseline_tag": baseline_tag,
        "n": n,
        "rows": rows,
        "cer_baseline": cer_baseline,
        "cer_corrected": cer_corrected,
        "abs_reduction": cer_baseline - cer_corrected,
        "rel_reduction": (cer_baseline - cer_corrected) / cer_baseline if cer_baseline else 0.0,
        "made_worse": made_worse,
        "n_was_correct": len(was_correct),
        "broke_correct": broke_correct,
        "n_changed": n_changed,
        "rejected_edits": rejected_edits,
        "parse_ok": parse_ok,
        "paraphrase_flag": paraphrase_flag,
        "base_arm_frac": base_arm,
        "corr_arm_frac": corr_arm,
        "len_ratio": len_ratio,
        "in_tokens": in_tok,
        "out_tokens": out_tok,
        "cost_page": cost_page,
        "cost_1000": cost_page * 1000,
    }


# ── Outputs ─────────────────────────────────────────────────────────────────────

def write_corrected_predictions(res: dict) -> Path:
    """Write corrected predictions in predict_lines.py format under a new tag, so
    analyze_errors.py can re-score them directly."""
    tag = f"{res['baseline_tag']}_llm_{res['modelshort']}_{res['mode']}"
    out_dir = PRED_BASE / tag / res["page"]
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = {
        r["id"]: {
            "column": r["column"],
            "pred_greedy": r["corrected"],
            "pred_beam": r["corrected"],
        }
        for r in res["rows"]
    }
    manifest = {
        "model_tag": tag,
        "corrected_from": res["baseline_tag"],
        "cli_model": res["cli_model"],
        "api_model": res["api_model"],
        "provider": res["provider"],
        "mode": res["mode"],
        "target": res["page"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "usage": {"input_tokens": res["in_tokens"], "output_tokens": res["out_tokens"]},
        "lines": lines,
    }
    (out_dir / "predictions.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out_dir / "predictions.json"


def stem_for(res: dict) -> str:
    return f"phase5_correction_{res['page']}_{res['modelshort']}_{res['mode']}"


def write_csv(res: dict, path: Path) -> None:
    cols = ["id", "column", "ref_len", "cer_baseline", "cer_corrected", "delta",
            "applied", "worse", "ref", "pred_beam", "corrected"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in res["rows"]:
            w.writerow({
                "id": r["id"], "column": r["column"], "ref_len": r["ref_len"],
                "cer_baseline": f"{r['cer']:.4f}", "cer_corrected": f"{r['cer_corrected']:.4f}",
                "delta": f"{r['cer_corrected'] - r['cer']:.4f}",
                "applied": r["applied"], "worse": r["cer_corrected"] > r["cer"] + 1e-9,
                "ref": r["ref"], "pred_beam": r["pred_beam"], "corrected": r["corrected"],
            })


def write_json(res: dict, path: Path) -> None:
    payload = {k: v for k, v in res.items() if k != "rows"}
    payload["rows"] = [
        {
            "id": r["id"], "column": r["column"], "ref_len": r["ref_len"],
            "cer_baseline": r["cer"], "cer_corrected": r["cer_corrected"],
            "applied": r["applied"], "ref": r["ref"],
            "pred_beam": r["pred_beam"], "corrected": r["corrected"],
        }
        for r in res["rows"]
    ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")


def write_html(res: dict, path: Path) -> None:
    """Contact sheet (extends analyze_errors.write_html style with a CORR line),
    sorted by lines the correction changed the most (worst-first within that)."""
    def img_src(png: Path) -> str:
        return "../" + png.relative_to(REPO).as_posix()

    rows = sorted(
        res["rows"],
        key=lambda r: (r["corrected"] == r["pred_beam"], -abs(r["cer_corrected"] - r["cer"]), -r["cer"]),
    )[:WORST_N]

    cards = []
    for r in rows:
        delta = r["cer_corrected"] - r["cer"]
        tag = "fixed" if delta < -1e-9 else ("worse" if delta > 1e-9 else "same")
        cards.append(
            f"<div class='card {tag}'>"
            f"<img src='{escape(img_src(r['png']))}' />"
            f"<div class=meta>{escape(r['id'])} · CER {r['cer']:.3f} → {r['cer_corrected']:.3f}"
            f" ({delta:+.3f}) · len {r['ref_len']}{'' if r['applied'] else ' · unchanged'}</div>"
            f"<div class=ref><b>REF </b>{escape(r['ref'])}</div>"
            f"<div class=pred><b>BASE</b> {escape(r['pred_beam'])}</div>"
            f"<div class=corr><b>CORR</b> {escape(r['corrected'])}</div>"
            f"</div>"
        )

    summary = (
        f"<p><b>{escape(res['page'])}</b> · {escape(res['cli_model'])} "
        f"[{escape(res['mode'])}] · lines {res['n']}</p>"
        f"<p><b>CER:</b> {res['cer_baseline']*100:.2f}% → {res['cer_corrected']*100:.2f}% "
        f"(Δ {res['abs_reduction']*100:+.2f} pts, {res['rel_reduction']*100:.0f}% rel)</p>"
        f"<p><b>Over-correction:</b> made worse {res['made_worse']}/{res['n']} · "
        f"broke already-correct {res['broke_correct']}/{res['n_was_correct']} · "
        f"changed {res['n_changed']}/{res['n']}</p>"
        f"<p class=sanity>parse_ok {res['parse_ok']} · rejected edits {res['rejected_edits']} · "
        f"Armenian frac {res['base_arm_frac']:.2f}→{res['corr_arm_frac']:.2f} · "
        f"len/ref {res['len_ratio']:.2f} · paraphrase_flag {res['paraphrase_flag']}</p>"
        f"<p class=sanity><b>Cost:</b> in {res['in_tokens']} / out {res['out_tokens']} tok · "
        f"${res['cost_page']:.4f}/page · ${res['cost_1000']:.2f}/1000 pages</p>"
    )

    html = f"""<!doctype html><meta charset=utf-8>
<title>{escape(stem_for(res))}</title>
<style>
 body {{ font-family: -apple-system, system-ui, sans-serif; background:#15161a; color:#e8e8ec; margin:1.5rem; }}
 h1 {{ font-size:1.2rem; }}
 .sanity {{ color:#9aa0ac; }}
 .card {{ background:#2a2c33; border:1px solid #3a3d46; border-radius:8px; padding:.6rem; margin:.5rem 0; }}
 .card.fixed {{ border-left:4px solid #4ec77a; }}
 .card.worse {{ border-left:4px solid #d9534f; }}
 .card img {{ background:#f4f4f4; max-width:100%; display:block; padding:4px; border-radius:4px; }}
 .meta {{ color:#9aa0ac; font-size:.8rem; margin:.3rem 0; }}
 .ref {{ font-size:1.2rem; }} .pred {{ font-size:1.1rem; color:#bfe3ff; }} .corr {{ font-size:1.1rem; color:#bff0c8; }}
 .ref b, .pred b, .corr b {{ color:#9aa0ac; font-size:.7rem; }}
</style>
<h1>Phase 5 correction — {escape(res['page'])} · {escape(res['cli_model'])} [{escape(res['mode'])}]</h1>
{summary}
<h3>Lines changed (most-changed first), top {len(cards)}</h3>
{''.join(cards)}
"""
    path.write_text(html, encoding="utf-8")


def update_summary(res: dict) -> None:
    """Maintain a rolling ledger keyed by (page, model, mode) and regenerate
    reports/phase5_correction_summary.{md,csv,json} (Step 4 roll-up)."""
    ledger_path = REPORTS / "phase5_correction_summary.json"
    ledger: dict[str, dict] = {}
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    key = f"{res['page']}|{res['cli_model']}|{res['mode']}"
    ledger[key] = {
        "page": res["page"], "model": res["cli_model"], "mode": res["mode"],
        "n": res["n"],
        "cer_baseline": res["cer_baseline"], "cer_corrected": res["cer_corrected"],
        "abs_reduction": res["abs_reduction"], "rel_reduction": res["rel_reduction"],
        "made_worse": res["made_worse"], "broke_correct": res["broke_correct"],
        "n_was_correct": res["n_was_correct"], "n_changed": res["n_changed"],
        "parse_ok": res["parse_ok"], "paraphrase_flag": res["paraphrase_flag"],
        "cost_page": res["cost_page"], "cost_1000": res["cost_1000"],
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")

    runs = sorted(ledger.values(), key=lambda r: (r["page"], r["model"], r["mode"]))
    cols = ["page", "model", "mode", "n", "cer_baseline", "cer_corrected",
            "abs_reduction", "rel_reduction", "made_worse", "broke_correct",
            "n_changed", "parse_ok", "paraphrase_flag", "cost_page", "cost_1000"]
    with (REPORTS / "phase5_correction_summary.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(runs)

    md = ["# Phase 5 — LLM correction summary\n",
          f"\n_Updated {datetime.now(timezone.utc).date()} · baseline vs corrected CER, "
          "over-correction, and per-page cost. Gate: page_0400 ≤0.3%; clear net reduction "
          "on page_0251/page_0499; over-correction ≈ 0._\n",
          "\n| page | model | mode | n | CER base | CER corr | Δ pts | rel | worse | broke✓ | changed | $/page | $/1k |",
          "\n|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for r in runs:
        md.append(
            f"\n| {r['page']} | {r['model']} | {r['mode']} | {r['n']} | "
            f"{r['cer_baseline']*100:.2f}% | {r['cer_corrected']*100:.2f}% | "
            f"{r['abs_reduction']*100:+.2f} | {r['rel_reduction']*100:.0f}% | "
            f"{r['made_worse']} | {r['broke_correct']} | {r['n_changed']} | "
            f"${r['cost_page']:.4f} | ${r['cost_1000']:.2f} |"
        )
    (REPORTS / "phase5_correction_summary.md").write_text("".join(md) + "\n", encoding="utf-8")


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--page", required=True, help="contiguous page, e.g. page_0400_human")
    parser.add_argument("--model", required=True, choices=list(MODELS),
                        help="LLM corrector model id")
    parser.add_argument("--mode", default="rewrite", choices=["rewrite", "minimal-edit"])
    parser.add_argument("--baseline-tag", default="scale_500",
                        help="prediction tag to correct (default: scale_500)")
    args = parser.parse_args()

    res = correct_page(args.page, args.model, args.mode, args.baseline_tag)

    REPORTS.mkdir(parents=True, exist_ok=True)
    pred_path = write_corrected_predictions(res)
    stem = stem_for(res)
    write_csv(res, REPORTS / f"{stem}.csv")
    write_json(res, REPORTS / f"{stem}.json")
    write_html(res, REPORTS / f"{stem}.html")
    update_summary(res)

    print(f"\n  {res['page']} · {res['cli_model']} [{res['mode']}]  (n={res['n']})")
    print(f"  CER  baseline {res['cer_baseline']*100:.2f}%  ->  corrected {res['cer_corrected']*100:.2f}%"
          f"   (Δ {res['abs_reduction']*100:+.2f} pts, {res['rel_reduction']*100:.0f}% rel)")
    print(f"  over-correction: made worse {res['made_worse']}/{res['n']} · "
          f"broke already-correct {res['broke_correct']}/{res['n_was_correct']} · "
          f"changed {res['n_changed']}/{res['n']}")
    print(f"  parse_ok {res['parse_ok']} · rejected edits {res['rejected_edits']} · "
          f"paraphrase_flag {res['paraphrase_flag']}")
    print(f"  cost: in {res['in_tokens']} / out {res['out_tokens']} tok · "
          f"${res['cost_page']:.4f}/page · ${res['cost_1000']:.2f}/1000 pages")
    print(f"  wrote {pred_path.relative_to(REPO)}")
    print(f"  wrote reports/{stem}.{{csv,json,html}} + phase5_correction_summary.*")


if __name__ == "__main__":
    main()
