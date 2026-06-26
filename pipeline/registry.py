"""
Stage dispatch tables — the swap points of the pipeline.

Four registries, one per stage, each mapping a human-readable implementation key to
a ``StageImpl``. This mirrors the ``MODELS`` / ``CALL_FN`` dispatch pattern in
ml_vision/scripts/llm_correct.py. To add a new approach (a better cropper, a new OCR
engine, a different corrector) you add ONE entry here plus its adapter in stages.py —
the orchestrator, CLI and artifact writers need no changes.

Each entry carries:
  - ``slug``  : the token used to name the run folder (so the folder records the approach)
  - ``venv``  : "base" | "ml"  — only OCR runs in the ml venv, via a subprocess hop
  - ``doc``   : one-line description, recorded verbatim in each run's run.json
  - ``run``   : the stage adapter callable (None for OCR / the no-op slicer)
  - ``meta``  : extra static data — OCR engines carry {script, tag}; correctors carry
                {params} (the model/mode baked into the approach)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pipeline import stages


@dataclass(frozen=True)
class StageImpl:
    slug: str
    venv: str
    doc: str
    run: Callable | None = None
    meta: dict = field(default_factory=dict)


# ── Stage 1: crop columns ────────────────────────────────────────────────────
CROPPERS: dict[str, StageImpl] = {
    "auto": StageImpl(
        "auto", "base", "headless two-column detect + crop + line-slice", stages.crop_auto
    ),
    "human": StageImpl(
        "human", "base", "use human-annotated line crops (labeling UI)", stages.crop_human
    ),
}

# ── Stage 2: line slicing ────────────────────────────────────────────────────
# Today the only slicer is the horizontal-projection crop_lines, which runs INSIDE
# the cropper (labeling_ui.pipeline.crop_columns_and_lines). The slot is kept open so
# a future segmenter (e.g. learned line detection) becomes a one-line addition.
SLICERS: dict[str, StageImpl] = {
    "projection": StageImpl(
        "proj", "base", "horizontal-projection crop_lines (runs inside the cropper)", None
    ),
}

# ── Stage 3: OCR (runs in .venv_ml — launched as a subprocess by the orchestrator)
OCR_ENGINES: dict[str, StageImpl] = {
    "trocr-scale500": StageImpl(
        "trocr500", "ml", "fine-tuned TrOCR (finetune_phase4_scale_500), beam-4", None,
        meta={"script": "ml_vision/scripts/predict_lines.py", "tag": "scale_500"},
    ),
    "tesseract": StageImpl(
        "tess", "ml", "calfa hye-tesseract, raw-line psm 13", None,
        meta={"script": "ml_vision/scripts/predict_lines_tesseract.py", "tag": "tesseract"},
    ),
}

# ── Stage 4: LLM correction ──────────────────────────────────────────────────
# The model + mode are baked into each entry's meta["params"]; config.correct.params
# can override them. "none" skips the LLM pass (baseline OCR is the final text).
CORRECTORS: dict[str, StageImpl] = {
    "gemini-minimal-edit": StageImpl(
        "gemini-min", "base", "gemini-3.1-pro minimal-edit (validated Phase-5 default)",
        stages.correct_llm,
        meta={"params": {"cli_model": "gemini-3.1-pro", "mode": "minimal-edit"}},
    ),
    "opus-rewrite": StageImpl(
        "opus-rw", "base", "claude-opus-4-8 whole-page rewrite",
        stages.correct_llm,
        meta={"params": {"cli_model": "claude-opus-4-8", "mode": "rewrite"}},
    ),
    "none": StageImpl(
        "nocorr", "base", "no LLM pass — baseline OCR is the final text",
        stages.correct_none,
    ),
}
