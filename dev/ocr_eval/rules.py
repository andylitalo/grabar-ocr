"""Deterministic fixes applied after OCR or correction (Phase 11).

Writes ``<engine>+rules`` beside any predictions file in the ceiling set, so the scorer
shows each engine with and without the rules. No model calls.

Rules (each from the maintainer's reading of the print, checked on the typed lines):
- **apostrophe-i**: the preposition ի standing alone is printed ՚ի (confirmed
  2026-10-09; 10 of 10 standalone ի in the first 87 typed lines). Tesseract never reads
  the ՚, and Paddle reads it only sometimes (as ASCII `'`). The correctors add it only
  sometimes: the base and v3 prompts never did, and on the 8,556 ceiling lines v4 writes
  it on 126 lines where neither engine had it, while the rule still changes 575 of v4's
  lines (2026-11-25).

    uv run python -m dev.ocr_eval.rules corr-gemini-3.1-pro-v3 paddle-calfa-tiny
"""

from __future__ import annotations

import argparse
import re

from . import common

# standalone ի (start of line or after a space, followed by a space/punctuation/end),
# not already preceded by an apostrophe
STANDALONE_I = re.compile(r"(^|\s)ի(?=\s|$|[։.,՝])")


def apply_rules(text: str) -> str:
    return STANDALONE_I.sub(lambda m: f"{m.group(1)}՚ի", text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("engines", nargs="+")
    ap.add_argument("--set", default="ceiling")
    a = ap.parse_args()
    common.use_set(a.set)
    for engine in a.engines:
        rec = common.load_predictions(engine)
        if not rec:
            raise SystemExit(f"no predictions for {engine}")
        try:
            common.hold(common.PREDICTIONS_DIR / f"{engine}+rules.json")
        except common.Busy as e:
            raise SystemExit(str(e))
        lines = {k: apply_rules(v) for k, v in rec["lines"].items()}
        changed = sum(lines[k] != v for k, v in rec["lines"].items())
        # every line is derived now, from `engine`'s current lines, with these settings
        common._write(f"{engine}+rules", {"from": engine, "rules": ["apostrophe-i"]}, lines,
                      uniform=True)
        print(f"{engine}+rules: {changed} of {len(lines)} lines changed")


if __name__ == "__main__":
    main()
