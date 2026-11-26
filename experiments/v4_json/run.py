"""v4-json: the v4 corrector answered as JSON under a Gemini response schema (2026-11-25).

Not adopted (see README.md next to this file). This script reruns the experiment on top of
the production corrector (``dev/ocr_eval/correct.py``), which it leaves untouched: same
prompt except the output-format sentence, same page text and line images, same checks on
each line's answer. Only the request (a response schema) and the reading of the answer
(JSON instead of `<number>\\t<text>` rows) differ.

It writes ``corr-gemini-3.1-pro-v4-json-rerun`` by default, never the committed predictions
of the measured run (``corr-gemini-3.1-pro-v4-json``). Like ``correct.py``, it fills only
the lines its predictions file doesn't have yet; ``--redo`` starts the file afresh. A page
with fallback lines is asked once more and the better attempt kept, as in the measured run
(today's ``correct.py`` asks again only when an answer is misaligned). The measured run
also re-asked lines that still fell back, ±3 lines; it fixed none of the 4, so this script
leaves that out.

    uv run python experiments/v4_json/run.py                  # 103 pages, ~$10
    uv run python experiments/v4_json/run.py --pages 453      # one page, a few cents
    uv run python -m dev.ocr_eval.rules corr-gemini-3.1-pro-v4-json-rerun
    uv run python -m dev.ocr_eval.ceiling score
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from dev.line_review import lines  # noqa: E402
from dev.line_review import transcribe as tr  # noqa: E402
from dev.ocr_eval import common  # noqa: E402
from dev.ocr_eval import correct as C  # noqa: E402

MODEL = "gemini-3.1-pro"
MEASURED = "corr-gemini-3.1-pro-v4-json"  # the committed predictions; never written here
RERUN = MEASURED + "-rerun"
FORMAT_JSON = ("- Return a JSON object with one key per line number, \"1\" up to the last line, in "
               "order, each the corrected text of that line, and nothing else.")
FORMAT_TSV = ("- Return EXACTLY the same line numbers in the same order, formatted as "
              "`<number>\\t<corrected text>`, one per line, and nothing else.")


def prompt() -> str:
    """v4's system prompt with only its output-format rule replaced."""
    if FORMAT_TSV not in C.PROMPTS["v4"]:
        raise SystemExit("v4's format rule changed in correct.py: this experiment no longer "
                         "applies as is (check out tag exp/v4-json-2026-11-25 for the original)")
    return C.PROMPTS["v4"].replace(FORMAT_TSV, FORMAT_JSON)


def call_gemini_json(model: str, user: str, system: str, images, n_lines: int) -> tuple[str, dict]:
    """``correct.call_gemini`` plus a response schema: keys "1".."N", all required, in order."""
    from google import genai
    from google.genai import types

    contents: list = [user]
    for n, png in images:
        contents += [f"Line {n}", types.Part.from_bytes(data=png, mime_type="image/png")]
    nums = [str(n) for n in range(1, n_lines + 1)]
    client = genai.Client(http_options=types.HttpOptions(timeout=C.HTTP_TIMEOUT_S * 1000))
    resp = client.models.generate_content(
        model=model, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=C.MAX_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_budget=C.GEMINI_THINKING_BUDGET),
            response_mime_type="application/json",
            response_schema=types.Schema(
                type=types.Type.OBJECT, properties={n: types.Schema(type=types.Type.STRING) for n in nums},
                required=nums, property_ordering=nums)))
    um = resp.usage_metadata
    return resp.text or "", {"in": um.prompt_token_count or 0, "out": um.candidates_token_count or 0,
                             "served_by": resp.model_version}


def parse_json(text: str, keys: list[str], preds: dict) -> tuple[dict[str, str], list[str]]:
    """Corrected text per key and the keys that fell back, under ``correct.parse``'s checks
    (a kept `A:`/`B:` label is stripped; a missing line, echoed readings or another line's
    text fall back to Paddle's reading). An answer that isn't a JSON object has no lines."""
    try:
        obj = json.loads(text)
    except ValueError:
        obj = {}
    got = {}
    for k, v in (obj.items() if isinstance(obj, dict) else []):
        if str(k).strip().isdigit():
            t = str(v).strip()
            got[int(k)] = t if "‖" in t else re.sub(r"^[AB]:\s*", "", t)
    out, bad = {}, []
    for n, k in enumerate(keys, 1):
        t = got.get(n, "")
        if t and "‖" not in t and not re.match(r"^[AB]:", t) and not C.drifted(t, k, preds):
            out[k] = t
        else:
            out[k] = preds[C.ENGINES[1]].get(k, "")
            bad.append(k)
    return out, bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", default=RERUN,
                    help="predictions file to fill (in the ceiling set)")
    ap.add_argument("--redo", action="store_true", help="start the predictions file afresh")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pages", type=int, nargs="*", help="only these pages (e.g. a one-page check)")
    a = ap.parse_args()
    if a.engine == MEASURED:
        raise SystemExit(f"{MEASURED} holds the measured run's predictions: write a new --engine")
    C._load_env()
    model = C.MODELS[MODEL][1]
    system = prompt()
    common.use_set(C.SET)
    preds = {e: common.load_predictions(e)["lines"] for e in C.ENGINES}
    sample = tr.load_sample(C.SET)
    pages = sorted({p["page"] for p in sample["picks"] if C.reference(p["id"]) is not None})
    if a.pages:
        pages = [p for p in pages if p in set(a.pages)]
    common.hold(common.PREDICTIONS_DIR / f"{a.engine}.json")
    settings = {"model": model, "provider": "gemini", "prompt_version": "v4-json", "prompt": system,
                "inputs": list(C.ENGINES), "output": "json", "experiment": "experiments/v4_json"}
    out = {} if a.redo else dict(common.load_predictions(a.engine).get("lines", {}))
    uniform = not out  # every line in the file is then made with these settings
    todo = [p for p in pages if any(l["key"] not in out for l in lines.page_lines(p))]
    print(f"{a.engine}: {len(todo)} pages to correct")
    total = {"in": 0, "out": 0, "fallback_keys": []}

    def do_page(page: int):
        page_lines = lines.page_lines(page)
        keys = [l["key"] for l in page_lines]
        images = C.page_images(page, page_lines, preds, "line")
        user = C.page_prompt(keys, preds)
        attempts, usage = [], {"in": 0, "out": 0}
        for n in (1, 2):  # once more while lines fall back; keep the better attempt
            text, u = C.with_retries(lambda: call_gemini_json(model, user, system, images, len(keys)))
            usage["in"] += u["in"]
            usage["out"] += u["out"]
            corrected, bad = parse_json(text, keys, preds)
            attempts.append((len(bad), n, corrected, bad))
            if not bad:
                break
        _, _, corrected, bad = min(attempts, key=lambda x: x[:2])
        return page, corrected, bad, usage

    start = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for i, (page, corrected, bad, usage) in enumerate(pool.map(do_page, todo), 1):
            out.update(C.new_lines(corrected, out))
            total["in"] += usage["in"]
            total["out"] += usage["out"]
            total["fallback_keys"] += bad
            common._write(a.engine, settings, out, uniform=uniform)
            print(f"  p{page}: {len(corrected)} lines, {len(bad)} fallback "
                  f"({i}/{len(todo)}, {(time.time() - start) / i:.0f} s/page)", flush=True)
    print(f"done: {total}")


if __name__ == "__main__":
    main()
