"""Deterministic fixes applied after OCR or correction (Phase 11).

Writes ``<engine>+rules`` beside any predictions file in the ceiling set, so the scorer
shows each engine with and without the rules. No model calls.

Rules (each from the maintainer's reading of the print, checked on the typed lines):
- **apostrophe-i**: the preposition ի standing alone is printed ՚ի (confirmed
  2026-10-09; 10 of 10 standalone ի in the first 87 typed lines). Both OCR engines often
  drop the ՚, and the LLM correctors don't add it.

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
        lines = {k: apply_rules(v) for k, v in rec["lines"].items()}
        changed = sum(lines[k] != v for k, v in rec["lines"].items())
        common._write(f"{engine}+rules", {"from": engine, "rules": ["apostrophe-i"]}, lines)
        print(f"{engine}+rules: {changed} of {len(lines)} lines changed")


if __name__ == "__main__":
    main()
