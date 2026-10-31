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
    uv run python -m dev.ocr_eval.correct --model gemini-3.1-pro --prompt v3   # A/B: + common errors
    uv run python -m dev.ocr_eval.correct --model gemini-3.1-pro --prompt v4   # + line images

v4 is v3 plus the image of each line where the engines disagree, so the model can look at
the disputed letters (Ձ vs Չ) where the meaning doesn't settle them. v5 shows the same
lines with their neighbours above and below in the image (the line outlined), for a word
broken across lines and for comparing letter shapes; the text of every line is in the
prompt in all versions.

    uv run python -m dev.ocr_eval.correct --model gemini-3.1-pro --prompt v5   # + neighbours
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from dev.line_review import crops, lines, storage
from dev.line_review import transcribe as tr

from . import common
from .ceiling import ENGINES, SET, reference
from .score import edits, normalize

# name -> (provider, API model id)
MODELS = {
    "opus-5.5": ("anthropic", "claude-opus-5-5"),
    "gemini-3.1-pro": ("gemini", "gemini-3.1-pro-preview"),
    "gemini-3.8-flash": ("gemini", "gemini-3.8-flash"),
    "gemini-4": ("gemini", "gemini-4-argon"),
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


# v3 = v2 + the errors this book's OCR makes most (from the engines' disagreements over the
# whole book; every example word also occurs outside the test samples). A/B against v2:
# does naming them help, and does it make the model alter correct lines?
COMMON_ERRORS = (
    "\n\nCOMMON ERRORS IN THIS BOOK. These may be fixed even where both readings agree, but only "
    "when the result is a correct Grabar word or the book's standard abbreviation. The goal is "
    "correct Grabar vocabulary and grammar exactly as printed, never modern spelling.\n"
    "1. Tone codes: a letter-numeral followed by Ձ (for ձայն): ԱՁ. ԲՁ. ԳՁ. ԴՁ., lowercase "
    "աձ. բձ. գձ. դձ.; the plagal tones use Կ: ԱԿ. ԲԿ. ԳԿ. ԴԿ., lowercase ակ. բկ. գկ. դկ. The OCR "
    "misreads this Ձ/ձ as Չ, Զ, 3 or ): ԱՉ. → ԱՁ., ԲԶ. → ԲՁ., գ3. → գձ., բ). → բձ.; also "
    "Չայն → Ձայն.\n"
    "2. Weekday codes: a letter-numeral followed by շ (from շաբթի): Բշ. Գշ. Դշ. Եշ.; also Կիր. "
    "Ուր. Շբ. The OCR misreads this շ as չ: Բչ. → Բշ., Գչ. → Գշ., Դչ. → Դշ.\n"
    "3. շ and չ are confused inside words: Ճաչու → Ճաշու, զաբաթ → շաբաթ, գիչերին → գիշերին.\n"
    "4. Other frequent misreads: Տէս → Տես (\"see\", in cross-references), Քարող → Քարոզ, "
    "տեղաոյս → տեղւոյս.\n"
    "5. The text has no Latin letters: a Latin letter is always a misread Armenian one "
    "(Փեsրուար → Փետրուար).\n"
    "6. The preposition ի standing alone is printed with an apostrophe before it: ՚ի. One OCR "
    "reading often drops it (ի → ՚ի) or writes it as ' (keep the apostrophe as given).\n"
    "Չ and Զ are correct in many words (Չորրորդ, Զկնի, Զատիկ): change them only in the codes "
    "above or where the result is clearly the correct Grabar word."
)
# v4 = v3 + the image of every line with two readings.
LINE_IMAGES = (
    "\n\nLINE IMAGES. After the lines, the scanned image of each line with two readings follows, "
    "labeled `Line <number>`. Look at the disputed letters in the image to choose between the "
    "readings: the image settles look-alike letters (Ձ/Չ/Զ, շ/չ, է/ե, գ/դ) that the meaning "
    "cannot. Transcribe what is printed; do not correct the printed text itself. The images "
    "are only evidence: still return EVERY line of the page, from 1 to the last, including the "
    "lines without an image, in the format above."
)
# v5 = v4 with each image showing the line between its neighbours.
CONTEXT_IMAGES = (
    "\n\nLINE IMAGES. After the lines, a scan of each line with two readings follows, labeled "
    "`Line <number>`. The line is outlined in orange; the lines above and below it are shown "
    "for context (a word broken across lines, and the same letters printed nearby). Look at "
    "the disputed letters in the outlined line to choose between the readings: the image "
    "settles look-alike letters (Ձ/Չ/Զ, շ/չ, է/ե, գ/դ) that the meaning cannot. Transcribe "
    "what is printed; do not correct the printed text itself. The images are only evidence: "
    "still return EVERY line of the page, from 1 to the last, including the lines without an "
    "image, in the format above."
)
PROMPTS = {"v2": SYSTEM, "v3": SYSTEM + COMMON_ERRORS, "v4": SYSTEM + COMMON_ERRORS + LINE_IMAGES,
           "v5": SYSTEM + COMMON_ERRORS + CONTEXT_IMAGES}
WITH_IMAGES = {"v4": "line", "v5": "context"}
CONTEXT_MARGIN = 1.3  # line heights above and below: one neighbour each side

Images = list[tuple[int, bytes]]  # (line number, PNG) for the lines with two readings


def _load_env() -> None:
    env = common.REPO_ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


# --- providers ---------------------------------------------------------------------


def call_anthropic(model: str, user: str, system: str = SYSTEM, images: Images = ()) -> tuple[str, dict]:
    import anthropic

    content: list[dict] = [{"type": "text", "text": user}]
    for n, png in images:
        content += [{"type": "text", "text": f"Line {n}"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                 "data": base64.b64encode(png).decode()}}]

    client = anthropic.Anthropic(timeout=HTTP_TIMEOUT_S)
    # Opus 5.5: thinking is always on (effort controls depth; default medium). Streaming
    # because a page plus thinking can run long. Server-side refusal fallback on by default.
    with client.beta.messages.stream(
        model=model, max_tokens=MAX_TOKENS, system=system,
        output_config={"effort": "medium"},
        # `fallbacks` via extra_body: the repo's SDK (0.107) predates the typed parameter.
        betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"refused: {msg.stop_details}")
    text = "".join(b.text for b in msg.content if b.type == "text")
    return text, {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens, "served_by": msg.model}


def call_gemini(model: str, user: str, system: str = SYSTEM, images: Images = ()) -> tuple[str, dict]:
    from google import genai
    from google.genai import types

    contents: list = [user]
    for n, png in images:
        contents += [f"Line {n}", types.Part.from_bytes(data=png, mime_type="image/png")]

    client = genai.Client(http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_S * 1000))
    resp = client.models.generate_content(
        model=model, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=MAX_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_budget=GEMINI_THINKING_BUDGET)))
    um = resp.usage_metadata
    return resp.text or "", {"in": um.prompt_token_count or 0, "out": um.candidates_token_count or 0,
                             "served_by": resp.model_version}


def call_openai(model: str, user: str, system: str = SYSTEM, images: Images = ()) -> tuple[str, dict]:
    from openai import OpenAI

    content: list[dict] = [{"type": "text", "text": user}]
    for n, png in images:
        content += [{"type": "text", "text": f"Line {n}"},
                    {"type": "image_url", "image_url": {
                        "url": "data:image/png;base64," + base64.b64encode(png).decode()}}]

    client = OpenAI(timeout=HTTP_TIMEOUT_S, max_retries=0)
    resp = client.chat.completions.create(
        model=model, max_completion_tokens=MAX_TOKENS, reasoning_effort="low",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": content}])
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


def disagrees(k: str, preds: dict[str, dict[str, str]]) -> bool:
    return normalize(preds[ENGINES[0]].get(k, "")) != normalize(preds[ENGINES[1]].get(k, ""))


def page_prompt(keys: list[str], preds: dict[str, dict[str, str]]) -> str:
    rows = []
    for n, k in enumerate(keys, 1):
        a, b = preds[ENGINES[0]].get(k, ""), preds[ENGINES[1]].get(k, "")
        rows.append(f"{n}\tA: {a} ‖ B: {b}" if disagrees(k, preds) else f"{n}\t{a}")
    return "\n".join(rows)


def page_images(page: int, page_lines: list[dict], preds: dict[str, dict[str, str]],
                kind: str = "line") -> Images:
    """For every line with two readings: its crop as the engines read it (``line``), or the
    line outlined between its neighbours (``context``)."""
    from PIL import Image

    render = Image.open(storage.render_path(page)).convert("L")
    out = []
    for n, line in enumerate(page_lines, 1):
        if disagrees(line["key"], preds):
            buf = io.BytesIO()
            img = (crops.line_crop(render, line) if kind == "line"
                   else crops.context_crop(render, line, page_lines, margin=CONTEXT_MARGIN))
            img.save(buf, format="PNG")
            out.append((n, buf.getvalue()))
    return out


LINE = re.compile(r"^\s*(\d+)\t(.*)$")
# A correction changes a few letters. A line further than this from both OCR readings is
# another line's text (the model skipped or merged a row and the numbering shifted).
MAX_CHANGE = 0.3  # share of the line's characters


def drifted(text: str, k: str, preds: dict[str, dict[str, str]]) -> bool:
    readings = [preds[e].get(k, "") for e in ENGINES]
    nearest = min(edits(normalize(r), normalize(text)) for r in readings)
    return nearest > max(4, MAX_CHANGE * max(len(normalize(r)) for r in readings))


def parse(text: str, keys: list[str], preds: dict[str, dict[str, str]]) -> tuple[dict[str, str], int]:
    """Corrected text per key; lines the model didn't return, returned still marked up as
    `A: … ‖ B: …`, or returned as some other line's text (``drifted``) fall back to the
    OCR (the agreed reading, else Paddle's).
    Returns (lines, number of fallbacks)."""
    got = {}
    for row in text.splitlines():
        m = LINE.match(row)
        if m:
            row_text = m.group(2).strip()
            if "‖" not in row_text:  # one reading chosen but its label kept: `B: …`
                row_text = re.sub(r"^[AB]:\s*", "", row_text)
            got[int(m.group(1))] = row_text
    out, fallbacks = {}, 0
    for n, k in enumerate(keys, 1):
        # A line that still carries the two-reading markers was echoed, not corrected.
        if (n in got and got[n] and "‖" not in got[n] and not re.match(r"^[AB]:", got[n])
                and not drifted(got[n], k, preds)):
            out[k] = got[n]
        else:
            out[k] = preds[ENGINES[1]].get(k, "")
            fallbacks += 1
    return out, fallbacks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=list(MODELS), required=True)
    ap.add_argument("--all", action="store_true", help="every sampled page, not only pages with typed lines")
    ap.add_argument("--prompt", choices=list(PROMPTS), default="v2",
                    help="v2: Phase 5 rules; v3: + this book's common errors with examples; "
                         "v4: v3 + images of the lines where the engines disagree; "
                         "v5: v4 with each image showing the neighbouring lines")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    _load_env()
    provider, model = MODELS[a.model]
    common.use_set(SET)
    preds = {e: common.load_predictions(e)["lines"] for e in ENGINES}
    sample = tr.load_sample(SET)
    pages = sorted({p["page"] for p in sample["picks"] if a.all or reference(p["id"]) is not None})

    system = PROMPTS[a.prompt]
    engine = f"corr-{a.model}" + ("" if a.prompt == "v2" else f"-{a.prompt}")
    old = common.load_predictions(engine)
    out = dict(old.get("lines", {})) if not a.redo else {}
    done_pages = {lines.page_of(k) for k in out}
    todo = [p for p in pages if p not in done_pages]
    print(f"{engine}: {len(todo)} pages to correct ({len(pages) - len(todo)} done)")
    usage = {"in": 0, "out": 0, "fallback_lines": 0, "pages": 0, "served_by": set()}

    def do_page(page: int):
        page_lines = lines.page_lines(page)
        keys = [l["key"] for l in page_lines]
        images = (page_images(page, page_lines, preds, WITH_IMAGES[a.prompt])
                  if a.prompt in WITH_IMAGES else [])
        total = {"in": 0, "out": 0}
        for attempt in (1, 2):  # a page with fallback lines is asked once more
            text, u = with_retries(lambda: CALL[provider](model, page_prompt(keys, preds), system, images))
            total["in"] += u["in"]   # every attempt is billed, not just the last
            total["out"] += u["out"]
            corrected, fallbacks = parse(text, keys, preds)
            if not fallbacks:
                break
            unparsed = [r for r in text.splitlines() if not LINE.match(r)][:3]
            print(f"  p{page}: {fallbacks} fallback lines (try {attempt}); "
                  f"{len(text.splitlines())} rows for {len(keys)} lines; unparsed: {unparsed}", flush=True)
        return page, corrected, fallbacks, {**u, **total}

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
            common._write(engine, {"model": model, "provider": provider, "prompt_version": a.prompt,
                                   "prompt": system,
                                   "inputs": list(ENGINES)}, out)
    usage["served_by"] = sorted(usage["served_by"])
    log = common.REPO_ROOT / "reports" / "phase11_correction_usage.json"
    runs = json.loads(log.read_text()) if log.exists() else []
    runs.append({"engine": engine, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **usage})
    log.write_text(json.dumps(runs, indent=1) + "\n")
    print(f"done: {usage}")


if __name__ == "__main__":
    main()
