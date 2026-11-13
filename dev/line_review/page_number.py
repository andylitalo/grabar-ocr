"""Find the printed page number in a paddle-filled baseline, so review starts with it marked.

The running header ``-( 459 )-`` is the page number (maintainer, 2026-10-11). On a
numbered page it is the topmost line: centred, small, above the double rule. Paddle
usually boxes it (its text reads like ``-( 459)``, digits often misread); where Paddle
missed it, a kraken fill covers the digits. Section openings and title pages put a
heading or a hymn's first line on top instead, which is wider or lower.

The value comes from the PDF page (printed = PDF − 4), never from Paddle's reading.
Thresholds are in render pixels (pp.453–643 render at ~2190 px wide) and were set from
the survey of every page's top line; ``tests/test_line_review_page_number.py`` checks the
whole book.
"""

from __future__ import annotations

import re

MAX_TOP = 300           # y of the box's top edge; numbers sit at 150-230
WIDTH = (80, 380)       # the full -( NNN )- is ~320; kraken fills over the digits ~95+
HEIGHT = (60, 130)      # ~90
CENTRE = (0.40, 0.60)   # box centre as a fraction of page width (alternates ~0.47 / ~0.53)
_NUMBER_TEXT = re.compile(r"[0-9()]")


def detect(seg: dict) -> str | None:
    """The key of the line that is the printed page number, or None."""
    if not seg["lines"]:
        return None
    top = min(seg["lines"], key=lambda l: l["bbox"][1])
    x1, y1, x2, y2 = top["bbox"]
    centre = (x1 + x2) / 2 / seg["width"]
    if not (y1 <= MAX_TOP and WIDTH[0] <= x2 - x1 <= WIDTH[1]
            and HEIGHT[0] <= y2 - y1 <= HEIGHT[1] and CENTRE[0] <= centre <= CENTRE[1]):
        return None
    if top.get("source") == "hyocr-paddle" and not _NUMBER_TEXT.search(top.get("text") or ""):
        return None
    return top["id"]


def auto_ops(seg: dict, value: str) -> list[dict]:
    """The ops a fresh review starts with: the detected page number (as ``value``), if any."""
    key = detect(seg)
    if key is None:
        return []
    return [{"op": "page_number", "line": key, "value": value, "auto": True}]
