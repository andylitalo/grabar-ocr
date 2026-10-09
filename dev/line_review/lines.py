"""Find a line by key, verified or not.

- ``p457.023``: a verified line (``data/verified_lines/page_457.json``), stable id.
- ``p520~line_013``: a line of a page not yet verified: the ``paddle-filled`` baseline
  with that page's review ops applied so far, under its materializer key. Used by the
  ceiling experiment (dev/ocr_eval/ceiling.py), which samples the whole book. These keys
  are not stable ids: re-running the baseline or changing the ops can move them.
"""

from __future__ import annotations

import json

from . import storage


def is_baseline_key(key: str) -> bool:
    return "~" in key


def page_of(key: str) -> int:
    return int(key[1:].split("~" if is_baseline_key(key) else ".")[0])


def page_lines(page: int) -> list[dict]:
    """The page's lines with a ``key``: verified ids if verified, else baseline keys."""
    if storage.load_review(page)["status"] == "verified" and storage.verified_path(page).exists():
        rec = json.loads(storage.verified_path(page).read_text(encoding="utf-8"))
        return [{**l, "key": l["id"]} for l in rec["lines"]]
    lines = storage.materialized(page, storage.load_review(page))
    return [{**l, "key": f"p{page}~{l['key']}"} for l in lines]


def find(key: str) -> tuple[dict, list[dict]]:
    """(the line, all lines of its page); KeyError if absent."""
    lines = page_lines(page_of(key))
    for line in lines:
        if line["key"] == key:
            return line, lines
    raise KeyError(key)
