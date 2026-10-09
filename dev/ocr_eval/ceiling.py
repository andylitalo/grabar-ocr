"""Ceiling experiment: how rarely do the two Calfa engines err, over the whole book?

Typing a random sample would mostly confirm lines both engines read correctly. Instead:

- **disagree**: a random sample of the lines where `tess-calfa-n` and `paddle-calfa-tiny`
  differ (after the scorer's normalization). At least one of them is wrong there. Over
  the book they disagree on 36.6% of lines (2.2% of characters), mostly look-alike
  Bolorgir letters (Չ/Ձ/Զ, չ/շ, զ/ղ, է/ե), far too many to type them all.
- **agree**: a random sample of the lines where they match. It measures the rarer case
  where both make the same mistake.

Each engine's error rate is the two strata's rates weighted by their share of the book,
and lines-per-error is its inverse. Lines come from every page: verified pages use their
verified lines, the rest the ``paddle-filled`` baseline (``dev/line_review/lines.py``);
a box that clips the text is marked Bad crop and left out.

    uv run python -m dev.ocr_eval.ceiling export          # crops for every line in the book
    .venv_ml/bin/python -m dev.ocr_eval.run_tesseract --model hye-calfa-n --set ceiling
    PYTHONPATH=. dev/lineseg_survey/.venv-hyocr/bin/python -m dev.ocr_eval.run_paddle --set ceiling
    uv run python -m dev.ocr_eval.ceiling sample          # writes data/transcriptions/ceiling/sample.json
    uv run python -m dev.ocr_eval.ceiling score           # writes reports/phase11_ceiling.md
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone

from PIL import Image

from dev.line_review import crops, lines, storage
from dev.line_review import transcribe as tr

from . import common
from .score import edits, normalize

SET = "ceiling"
ENGINES = ("tess-calfa-n", "paddle-calfa-tiny")
DISAGREE_SAMPLE = 300
AGREE_SAMPLE = 200
EXCLUDED_PAGES = {641}  # the Paschal table
BOOTSTRAP, SEED = 2000, 11


def export() -> None:
    common.use_set(SET)
    common.CROPS_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for page in storage.list_pages():
        if page in EXCLUDED_PAGES:
            continue
        page_lines = lines.page_lines(page)
        if not page_lines:
            continue
        render = Image.open(storage.render_path(page)).convert("L")
        for line in page_lines:
            path = common.CROPS_DIR / f"{line['key']}.png"
            if not path.exists():
                crops.line_crop(render, line).save(path)
                n += 1
    print(f"{n} new crops in {common.CROPS_DIR}")


def _predictions() -> dict[str, dict[str, str]]:
    common.use_set(SET)
    preds = {e: common.load_predictions(e).get("lines", {}) for e in ENGINES}
    if not all(preds.values()):
        raise SystemExit(f"Run both engines with --set {SET} first: {', '.join(ENGINES)}")
    return preds


def sample() -> None:
    preds = _predictions()
    keys = sorted(set(preds[ENGINES[0]]) & set(preds[ENGINES[1]]))
    agree, disagree = [], []
    for k in keys:
        a, b = (normalize(preds[e][k]) for e in ENGINES)
        (agree if a == b else disagree).append(k)
    agree_pick = sorted(agree, key=lambda k: tr.rank(tr.SEED, k))[:AGREE_SAMPLE]
    disagree_pick = sorted(disagree, key=lambda k: tr.rank(tr.SEED, k))[:DISAGREE_SAMPLE]
    picks = [{"id": k, "stratum": "disagree", "page": lines.page_of(k)} for k in disagree_pick]
    picks += [{"id": k, "stratum": "agree", "page": lines.page_of(k)} for k in agree_pick]
    rec = {"seed": tr.SEED, "engines": list(ENGINES),
           "population": {"agree": len(agree), "disagree": len(disagree)},
           "quotas": {"disagree": len(disagree_pick), "agree": len(agree_pick)},
           "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "picks": picks}
    tr.save_sample(rec, SET)
    path = tr.sample_path(SET)
    print(f"{len(keys)} lines: {len(agree)} agree, {len(disagree)} disagree "
          f"({100 * len(disagree) / len(keys):.1f}%). Sample: {len(picks)} lines "
          f"({len(disagree_pick)} disagreements + {len(agree_pick)} agreements) -> {path}")


def reference(key: str) -> str | None:
    """The human transcription, or None if untyped, illegible or a bad crop."""
    rec = tr.effective_line(key, SET)
    return rec["text"] if rec and rec["status"] == "done" else None


def score() -> None:
    preds = _predictions()
    smp = tr.load_sample(SET)
    pop = smp["population"]
    total = pop["agree"] + pop["disagree"]
    typed = {p["id"]: (p["stratum"], reference(p["id"])) for p in smp["picks"]}
    typed = {k: v for k, v in typed.items() if v[1] is not None}

    def wrong(engine: str, key: str) -> bool:
        return edits(normalize(typed[key][1], spaces=False),
                     normalize(preds[engine][key], spaces=False)) > 0

    def rate(engine: str, keys_by_stratum: dict[str, list[str]]) -> float:
        """Weighted line error rate; NaN until every populated stratum has a typed line."""
        out = 0.0
        for stratum, ks in keys_by_stratum.items():
            if not ks:
                if pop[stratum]:
                    return float("nan")
                continue
            out += pop[stratum] / total * sum(wrong(engine, k) for k in ks) / len(ks)
        return out

    by = {s: [k for k, (st, _) in typed.items() if st == s] for s in ("disagree", "agree")}
    out = ["# Phase 11: ceiling of the Calfa engines (provisional)", "",
           f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by "
           "`dev/ocr_eval/ceiling.py`. A line counts as wrong if any character differs after "
           "normalization (look-alike punctuation folded, spaces ignored).", "",
           f"Book: {total} lines; the engines disagree on {pop['disagree']} "
           f"({100 * pop['disagree'] / total:.1f}%). Typed so far: {len(by['disagree'])} of "
           f"{smp['quotas']['disagree']} disagreements, {len(by['agree'])} of "
           f"{smp['quotas']['agree']} agreements.", "",
           "| engine | wrong on disagree | wrong on agree | est. line error rate | ≈ lines per error | 95% interval (lines per error) |",
           "|---|--:|--:|--:|--:|--:|"]
    rng = random.Random(SEED)
    for e in ENGINES:
        r = rate(e, by)
        boots = sorted(rate(e, {s: [rng.choice(ks) for _ in ks] for s, ks in by.items()})
                       for _ in range(BOOTSTRAP))
        lo, hi = boots[int(0.025 * BOOTSTRAP)], boots[int(0.975 * BOOTSTRAP) - 1]
        def per(x: float) -> str:
            return "–" if x != x else "∞" if x == 0 else f"{1 / x:,.0f}"

        out.append(f"| `{e}` | {sum(wrong(e, k) for k in by['disagree'])}/{len(by['disagree'])} | "
                   f"{sum(wrong(e, k) for k in by['agree'])}/{len(by['agree'])} | "
                   f"{'–' if r != r else f'{100 * r:.2f}%'} | {per(r)} | {'–' if r != r else f'{per(hi)}–{per(lo)}'} |")
    out += ["", "## Agreed but wrong (both engines made the same mistake)", ""]
    both = [k for k in by["agree"] if wrong(ENGINES[0], k)]
    out += [f"- `{k}`: ref `{typed[k][1]}`, both `{preds[ENGINES[0]][k]}`" for k in both] or ["- none yet"]
    path = common.REPO_ROOT / "reports" / "phase11_ceiling.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out[4:8 + len(ENGINES)]))
    print(f"\nreport: {path.relative_to(common.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["export", "sample", "score"])
    {"export": export, "sample": sample, "score": score}[ap.parse_args().step]()


if __name__ == "__main__":
    main()
