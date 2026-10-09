"""LLM post-correction of the two Calfa engines' output, page by page (Phase 11).

Each page's lines go to the model in reading order. Where `tess-calfa-n` and
`paddle-calfa-tiny` agree, the line is shown once; where they disagree, both readings are
shown (`A: … ‖ B: …`). The model returns every line corrected, under Phase 5's v2 rules
(fix only look-alike letters inside words; never punctuation, spacing, digits,
letter-numerals, abbreviations or case; when unsure, leave it). Output is a predictions
file in the ceiling set, `data/ocr_predictions/ceiling/corr-<model>.json`, scored by
`ceiling.py score` like any engine.

Only pages holding typed ceiling lines are corrected (the rest can't be scored); pass
``--all`` for every sampled page.

    uv run python -m dev.ocr_eval.correct --model opus-5.5
    uv run python -m dev.ocr_eval.correct --model gemini-3.1-pro
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from dev.line_review import lines
from dev.line_review import transcribe as tr

from . import common
from .ceiling import ENGINES, SET, reference
from .score import normalize

# name -> (provider, API model id)
MODELS = {
    "opus-5.5": ("anthropic", "claude-opus-5-5"),
    "gemini-3.1-pro": ("gemini", "gemini-3.1-pro-preview"),
    "gemini-3.8-flash": ("gemini", "gemini-3.8-flash"),
    "gpt-6.1": ("openai", "gpt-6.1-sol"),
}
MAX_TOKENS = 32_000
GEMINI_THINKING_BUDGET = 512  # Phase 5b: same answers as dynamic thinking, ~10x faster
HTTP_TIMEOUT_S = 300

SYSTEM = (
    "You correct OCR of Classical Armenian (Grabar) printed in Bolorgir script, from a 1915 "
    "Jerusalem edition of the Tonatsuyts (a liturgical calendar and lectionary). You are given "
    "the lines of one page, numbered in reading order. Two independent OCR engines read each "
    "line. Where they agree, the line is shown once. Where they disagree, both readings are "
    "shown as `A: <reading> ‖ B: <reading>`; at least one of them is wrong there, almost always "
    "by a look-alike letter (e.g. Չ↔Ձ↔Զ, չ↔շ, զ↔ղ, է↔ե, գ↔դ, տ↔ա, ի↔ե, ծ↔յ, ո↔օ, or a digit or "
    "bracket read for ձ). Use the meaning of the Grabar across the lines to decide.\n\n"
    "STRICT RULES:\n"
    "- For a line with two readings, output the correct one. Combine them only where each is "
    "right in a different place.\n"
    "- For a line shown once, change it ONLY to fix a letter INSIDE a multi-letter word that is "
    "clearly a misread of a look-alike letter. Otherwise return it unchanged.\n"
    "- Do NOT paraphrase, translate, modernize spelling, reorder, or add or remove content.\n"
    "- Do NOT touch punctuation or spacing (period, comma, `։`, `՟`, `·`, `՞`, `՛`, `՚`, `՝`, "
    "hyphen, space) unless the two readings differ there.\n"
    "- Do NOT change digits, letter-numerals, or short abbreviations such as `ժ.`, `վ.`, `ԺԱ.`, "
    "`դկ.`, and never change any letter's case, unless the two readings differ there.\n"
    "- When unsure, LEAVE IT UNCHANGED (for two readings: prefer the one that is real Grabar).\n"
    "- Return EXACTLY the same line numbers in the same order, formatted as "
    "`<number>\\t<corrected text>`, one per line, and nothing else."
)


def _load_env() -> None:
    env = common.REPO_ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


# --- providers ---------------------------------------------------------------------


def call_anthropic(model: str, user: str) -> tuple[str, dict]:
    import anthropic

    client = anthropic.Anthropic(timeout=HTTP_TIMEOUT_S)
    # Opus 5.5: thinking is always on (effort controls depth; default medium). Streaming
    # because a page plus thinking can run long. Server-side refusal fallback on by default.
    with client.beta.messages.stream(
        model=model, max_tokens=MAX_TOKENS, system=SYSTEM,
        output_config={"effort": "medium"},
        # `fallbacks` via extra_body: the repo's SDK (0.107) predates the typed parameter.
        betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"},
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"refused: {msg.stop_details}")
    text = "".join(b.text for b in msg.content if b.type == "text")
    return text, {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens, "served_by": msg.model}


def call_gemini(model: str, user: str) -> tuple[str, dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_S * 1000))
    resp = client.models.generate_content(
        model=model, contents=user,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM, max_output_tokens=MAX_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_budget=GEMINI_THINKING_BUDGET)))
    um = resp.usage_metadata
    return resp.text or "", {"in": um.prompt_token_count or 0, "out": um.candidates_token_count or 0,
                             "served_by": resp.model_version}


def call_openai(model: str, user: str) -> tuple[str, dict]:
    from openai import OpenAI

    client = OpenAI(timeout=HTTP_TIMEOUT_S, max_retries=0)
    resp = client.chat.completions.create(
        model=model, max_completion_tokens=MAX_TOKENS, reasoning_effort="low",
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
    return resp.choices[0].message.content or "", {
        "in": resp.usage.prompt_tokens, "out": resp.usage.completion_tokens, "served_by": resp.model}


CALL = {"anthropic": call_anthropic, "gemini": call_gemini, "openai": call_openai}


def with_retries(fn, attempts: int = 3):
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - provider error types differ
            if attempt == attempts - 1:
                raise
            print(f"  retry after {type(e).__name__}: {str(e)[:120]}", flush=True)
            time.sleep(10 * (attempt + 1))


# --- pages -------------------------------------------------------------------------


def page_prompt(keys: list[str], preds: dict[str, dict[str, str]]) -> str:
    rows = []
    for n, k in enumerate(keys, 1):
        a, b = preds[ENGINES[0]].get(k, ""), preds[ENGINES[1]].get(k, "")
        rows.append(f"{n}\t{a}" if normalize(a) == normalize(b) else f"{n}\tA: {a} ‖ B: {b}")
    return "\n".join(rows)


LINE = re.compile(r"^\s*(\d+)\t(.*)$")


def parse(text: str, keys: list[str], preds: dict[str, dict[str, str]]) -> tuple[dict[str, str], int]:
    """Corrected text per key; lines the model didn't return fall back to the OCR
    (the agreed reading, else Paddle's). Returns (lines, number of fallbacks)."""
    got = {}
    for row in text.splitlines():
        m = LINE.match(row)
        if m:
            got[int(m.group(1))] = m.group(2).strip()
    out, fallbacks = {}, 0
    for n, k in enumerate(keys, 1):
        if n in got and got[n]:
            out[k] = got[n]
        else:
            out[k] = preds[ENGINES[1]].get(k, "")
            fallbacks += 1
    return out, fallbacks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=list(MODELS), required=True)
    ap.add_argument("--all", action="store_true", help="every sampled page, not only pages with typed lines")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    _load_env()
    provider, model = MODELS[a.model]
    common.use_set(SET)
    preds = {e: common.load_predictions(e)["lines"] for e in ENGINES}
    sample = tr.load_sample(SET)
    pages = sorted({p["page"] for p in sample["picks"] if a.all or reference(p["id"]) is not None})

    engine = f"corr-{a.model}"
    old = common.load_predictions(engine)
    out = dict(old.get("lines", {})) if not a.redo else {}
    done_pages = {lines.page_of(k) for k in out}
    todo = [p for p in pages if p not in done_pages]
    print(f"{engine}: {len(todo)} pages to correct ({len(pages) - len(todo)} done)")
    usage = {"in": 0, "out": 0, "fallback_lines": 0, "pages": 0, "served_by": set()}

    def do_page(page: int):
        keys = [l["key"] for l in lines.page_lines(page)]
        text, u = with_retries(lambda: CALL[provider](model, page_prompt(keys, preds)))
        corrected, fallbacks = parse(text, keys, preds)
        return page, corrected, fallbacks, u

    start = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(do_page, p) for p in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                page, corrected, fallbacks, u = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  page failed: {type(e).__name__}: {str(e)[:160]}", flush=True)
                continue
            out.update(corrected)
            usage["in"] += u["in"]
            usage["out"] += u["out"]
            usage["fallback_lines"] += fallbacks
            usage["pages"] += 1
            usage["served_by"].add(u["served_by"])
            print(f"  p{page}: {len(corrected)} lines, {fallbacks} fallback "
                  f"({n}/{len(todo)}, {(time.time() - start) / n:.0f} s/page)", flush=True)
            common._write(engine, {"model": model, "provider": provider, "prompt": SYSTEM,
                                   "inputs": list(ENGINES)}, out)
    usage["served_by"] = sorted(usage["served_by"])
    log = common.REPO_ROOT / "reports" / "phase11_correction_usage.json"
    runs = json.loads(log.read_text()) if log.exists() else []
    runs.append({"engine": engine, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **usage})
    log.write_text(json.dumps(runs, indent=1) + "\n")
    print(f"done: {usage}")


if __name__ == "__main__":
    main()
