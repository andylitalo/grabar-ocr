"""
CER scoring + missing-ground-truth detection.

Ground truth lives in the line .txt files written through the labeling UI
(``data/lines/page_XXXX_<method>/<region>/line_NNN.txt``). ``storage.list_lines``
already surfaces each line's labeled text and status, so scoring is a thin join of
that text against the pipeline's corrected output, with char-level CER from jiwer
(the project metric). When a page has no labeled lines (e.g. the auto-sliced
486/487 today), we emit an explicit "label these" instruction instead of silently
skipping — the scorecard only appears once ground truth exists.
"""

from __future__ import annotations

from jiwer import cer

from labeling_ui import storage


def _labeled_refs(page_id: str) -> dict[str, str]:
    """{line_id -> reference text} for labeled, non-empty lines of a page."""
    info = storage.list_lines(page_id)
    return {
        ln["line_id"]: ln["text"].strip()
        for ln in info["lines"]
        if ln["status"] == "labeled" and ln["text"].strip()
    }


def detect_needs_labeling(page_id: str) -> str | None:
    """Instruction string if the page has no ground truth, else None."""
    info = storage.list_lines(page_id)
    if info["counts"]["labeled"] > 0:
        return None
    total = info["counts"]["total"]
    return (
        f"{page_id}: no ground truth — {total} lines have no transcription. "
        f"To score CER, label them in the labeling UI "
        f"(data/lines/{page_id}/<region>/line_NNN.txt), then re-run the same config. "
        f"Note: nonchar_truth.json is a non-character verdict, NOT a transcription."
    )


def score_page(page_id: str, rows: list[dict]) -> dict | None:
    """Compute per-line + corpus CER for a page, mutating rows in place.

    Sets ``ref`` and ``cer`` on every row that has a labeled reference. Returns a
    page-level summary ``{page_id, n_scored, cer}`` (char-weighted corpus CER), or
    None when the page has no ground truth.
    """
    refs_by_id = _labeled_refs(page_id)
    if not refs_by_id:
        return None

    refs: list[str] = []
    hyps: list[str] = []
    for r in rows:
        ref = refs_by_id.get(r["line_id"])
        if ref is None:
            continue
        hyp = r["corrected"]
        r["ref"] = ref
        r["cer"] = round(cer(ref, hyp), 4)
        refs.append(ref)
        hyps.append(hyp)

    corpus = cer(refs, hyps) if refs else None
    return {"page_id": page_id, "n_scored": len(refs), "cer": round(corpus, 4) if corpus is not None else None}
