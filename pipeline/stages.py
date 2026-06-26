"""
Stage adapters — thin wrappers that present each existing stage function under one
uniform contract so the orchestrator can treat all stages alike.

NO OCR / cropping / LLM logic lives here; every adapter delegates to a tested module
(``data_prep.auto_slice``, ``ml_vision/scripts/predict_lines.py``,
``ml_vision/scripts/digitize_page.py``). External imports are lazy (inside each
function) so merely importing the pipeline package never pulls cv2/torch/SDKs.

Adapter contracts
-----------------
crop_*(n, *, force=False, **params) -> dict
    {"page_id", "deferred": bool, "reason": str, "status": str, ...}
    A deferred page is surfaced, never silently dropped (it needs manual work).
correct_*(page_id, *, baseline_tag, force=False, **params) -> dict
    {"correct_tag": str, "skipped": bool}
    OCR (stage 3) has no adapter here — it crosses the .venv_ml interpreter boundary
    and is launched as a subprocess by the orchestrator from each engine's registry
    ``meta`` (script + tag).
"""

from __future__ import annotations


# ── Stage 1+2: crop columns + line-slice (base venv) ─────────────────────────
def crop_auto(n: int, *, force: bool = False, **params) -> dict:
    """Headless two-column detect + crop + line-slice via data_prep.auto_slice.

    Idempotent like the OCR/correct stages: if auto line crops already exist they
    are reused (never re-sliced) unless ``force``. This protects validated existing
    slices from being clobbered by a re-detect — the conservative Phase-6 detector
    can yield a different (or deferred) result on the same page. Pages the detector
    is not confident about are returned as ``deferred`` (route to manual region
    annotation in the labeling UI) — mirrors auto_slice.main.
    """
    from labeling_ui import storage

    page_id = storage.page_artifact_id(n, storage.METHOD_AUTO)
    if not force and storage.has_auto_lines(n):
        return {"page_id": page_id, "deferred": False,
                "reason": "reused existing auto line crops (use --force to re-slice)",
                "status": "reused"}

    from data_prep.auto_slice import auto_slice_page

    res = auto_slice_page(n, persist_boxes=True, dry_run=False, force=force)
    return {
        "page_id": res["page_id"],
        "deferred": not res["confident"],
        "reason": res.get("reason", ""),
        "status": res.get("status", ""),
        "line_counts": res.get("line_counts"),
    }


def crop_human(n: int, *, force: bool = False, **params) -> dict:
    """Use human-annotated line crops if they already exist; otherwise defer.

    The human method tag (page_XXXX_human) is produced through the labeling UI. We
    don't re-crop here — if the human line tree exists we run on it, else we defer
    with a clear instruction so the page is never silently skipped.
    """
    from labeling_ui import storage

    page_id = storage.page_artifact_id(n, storage.METHOD_HUMAN)
    if storage.list_region_dirs(page_id):
        return {"page_id": page_id, "deferred": False,
                "reason": "existing human line crops", "status": "human-existing"}
    return {
        "page_id": page_id,
        "deferred": True,
        "reason": "no human annotation; annotate in the labeling UI or use --crop auto",
        "status": "deferred",
    }


# ── Stage 4: LLM correction (base venv) ──────────────────────────────────────
def correct_llm(
    page_id: str,
    *,
    baseline_tag: str,
    cli_model: str = "gemini-3.1-pro",
    mode: str = "minimal-edit",
    force: bool = False,
    **params,
) -> dict:
    """Whole-page LLM correction via digitize_page.digitize + write_outputs.

    Reuses the production digitizer unchanged (same prompts/clients/parse as the
    evaluated path). Idempotent: an existing corrected predictions.json is reused
    unless ``force`` (avoids re-spending API tokens on re-runs).
    """
    import digitize_page as digitize

    short = digitize.lc.MODELS[cli_model][2]
    correct_tag = f"{baseline_tag}_llm_{short}_{mode}"
    out_json = digitize.PRED_BASE / correct_tag / page_id / "predictions.json"
    if out_json.exists() and not force:
        return {"correct_tag": correct_tag, "skipped": True}

    res = digitize.digitize(page_id, cli_model, mode, baseline_tag)
    digitize.write_outputs(res)
    return {"correct_tag": correct_tag, "skipped": False}


def correct_none(page_id: str, *, baseline_tag: str, **params) -> dict:
    """No LLM pass — the corrected text is the baseline OCR beam itself."""
    return {"correct_tag": baseline_tag, "skipped": True}
