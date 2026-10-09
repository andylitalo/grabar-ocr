"""Score every engine in data/ocr_predictions/ against the Phase 10 test set.

Writes reports/phase11_ocr_comparison.md and prints the main table. Every engine is
scored on the same lines: transcribed (status ``done``) and predicted by all engines.

    uv run python -m dev.ocr_eval.score
"""

from __future__ import annotations

import json
import random
import unicodedata
from datetime import datetime, timezone

import jiwer

from dev.line_review import transcribe as tr

from .common import PREDICTIONS_DIR, REPO_ROOT

REPORT = REPO_ROOT / "reports" / "phase11_ocr_comparison.md"
ABBREVIATION_MARK = "՟"
# Look-alike punctuation counts as one character (Phase 10 decision, 2026-10-04).
# Apostrophes too: the print's ՚ (as in ՚ի) comes out of Paddle as ASCII '.
FOLD = str.maketrans({"֊": "-", "‐": "-", "–": "-", "—": "-", "․": ".", "։": ":",
                      "'": "՚", "’": "՚"})
BOOTSTRAP, SEED = 2000, 11


def normalize(text: str, fold: bool = True, spaces: bool = True) -> str:
    """NFC, look-alike punctuation folded, whitespace collapsed (or dropped: spacing
    around punctuation is ambiguous on this print, e.g. ``Բ. 11.`` vs ``Բ . 11 .``)."""
    text = unicodedata.normalize("NFC", text)
    if fold:
        text = text.translate(FOLD)
    return " ".join(text.split()) if spaces else "".join(text.split())


def edits(ref: str, hyp: str) -> int:
    if not ref:
        return len(hyp)
    if not hyp:
        return len(ref)
    out = jiwer.process_characters(ref, hyp)
    return out.substitutions + out.deletions + out.insertions


def pooled(rows: list[tuple[int, int]]) -> float:
    total = sum(n for _, n in rows)
    return sum(e for e, _ in rows) / total if total else float("nan")


def interval(rows: list[tuple[int, int]]) -> tuple[float, float]:
    """95% bootstrap interval over lines for the pooled CER."""
    if len(rows) < 2:
        return float("nan"), float("nan")
    rng = random.Random(SEED)
    stats = sorted(pooled([rng.choice(rows) for _ in rows]) for _ in range(BOOTSTRAP))
    return stats[int(0.025 * BOOTSTRAP)], stats[int(0.975 * BOOTSTRAP) - 1]


def load() -> tuple[dict, dict, dict]:
    """(references {id: text}, strata {id: stratum}, predictions {engine: {id: text}})."""
    sample = tr.load_sample()
    strata = {p["id"]: p["stratum"] for p in sample["picks"]}
    refs, rechecks = {}, {}
    for page in sorted({p["page"] for p in sample["picks"]}):
        for lid, rec in tr.load_page(page).items():
            if lid in strata and rec["status"] == "done":
                refs[lid] = rec["text"]
                if "recheck" in rec:
                    rechecks[lid] = rec["recheck"]["text"]
    preds = {}
    for path in sorted(PREDICTIONS_DIR.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        preds[rec["engine"]] = rec["lines"]
    return {"refs": refs, "rechecks": rechecks}, strata, preds


def pct(x: float) -> str:
    return "–" if x != x else f"{100 * x:.1f}%"


def main() -> None:
    data, strata, preds = load()
    refs = data["refs"]
    engines = sorted(preds)
    common = sorted(lid for lid in refs if all(lid in preds[e] for e in engines))
    if not common:
        raise SystemExit("No transcribed line has predictions from every engine yet.")

    def rows(engine: str, ids: list[str], fold: bool = True, spaces: bool = True) -> list[tuple[int, int]]:
        return [(edits(normalize(refs[i], fold, spaces), normalize(preds[engine][i], fold, spaces)),
                 len(normalize(refs[i], fold, spaces))) for i in ids]

    main_rows = {e: rows(e, common) for e in engines}
    ranked = sorted(engines, key=lambda e: pooled(main_rows[e]))
    chars = sum(n for _, n in main_rows[engines[0]])

    out = [f"# Phase 11: OCR engine comparison (provisional)", "",
           f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by "
           f"`dev/ocr_eval/score.py`. Plan: `docs/phase_11_ocr_comparison.md`.", "",
           f"**{len(common)} lines, {chars} characters**, scored identically for every engine "
           f"(of {len(refs)} transcribed). CER is pooled over lines; look-alike punctuation is "
           "folded. Intervals are 95% bootstrap over lines: where they overlap, the ranking "
           "isn't settled.", "",
           "| engine | CER | 95% interval | spaces ignored | raw (no folding) |", "|---|--:|--:|--:|--:|"]
    for e in ranked:
        lo, hi = interval(main_rows[e])
        out.append(f"| `{e}` | **{pct(pooled(main_rows[e]))}** | {pct(lo)}–{pct(hi)} | "
                   f"{pct(pooled(rows(e, common, spaces=False)))} | "
                   f"{pct(pooled(rows(e, common, fold=False)))} |")

    groups = {name: [i for i in common if strata[i] == name] for name in tr.QUOTAS}
    groups["with ՟"] = [i for i in common if ABBREVIATION_MARK in refs[i]]
    groups["without ՟"] = [i for i in common if ABBREVIATION_MARK not in refs[i]]
    groups = {k: v for k, v in groups.items() if v}
    out += ["", "## Breakdown", "", "| engine | " + " | ".join(f"{k} (n={len(v)})" for k, v in groups.items()) + " |",
            "|---|" + "--:|" * len(groups)]
    for e in ranked:
        out.append(f"| `{e}` | " + " | ".join(pct(pooled(rows(e, v))) for v in groups.values()) + " |")

    rc = data["rechecks"]
    out += ["", "## Noise floor", ""]
    if rc:
        nf = [(edits(normalize(refs[i]), normalize(t)), len(normalize(refs[i]))) for i, t in rc.items()]
        out.append(f"CER between the two human passes on {len(rc)} rechecked lines: **{pct(pooled(nf))}**. "
                   "Engine differences smaller than this don't count.")
    else:
        out.append("No blind rechecks yet.")

    out += ["", "## Worst lines per engine", ""]
    for e in ranked:
        def line_cer(i: str) -> float:
            return edits(normalize(refs[i]), normalize(preds[e][i])) / max(1, len(normalize(refs[i])))

        worst = [i for i in sorted(common, key=line_cer, reverse=True) if line_cer(i) > 0][:3]
        out += [f"**`{e}`**", ""]
        if not worst:
            out.append("- no errors")
        for i in worst:
            out += [f"- `{i}` ({strata[i]})", f"  - ref: {refs[i]}", f"  - hyp: {preds[e][i]}"]
        out.append("")

    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out[:8 + len(ranked)]))
    print(f"\nreport: {REPORT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
