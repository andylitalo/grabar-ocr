"""
Modular digitization pipeline: page numbers in, Grabar text out.

Four swappable stages — crop / slice / OCR / correct — chained over existing,
tested stage functions. Importing this package puts the repo root and the ML
scripts dir on sys.path (the project's import convention; it is not pip-installed)
so the stage adapters can reach data_prep / labeling_ui / ml_vision.scripts.

Usage:
    from pipeline import run_pages
    out = run_pages([486, 487])            # default config
    print(out["merged_text"])              # combined doc for translation
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "ml_vision" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from pipeline.api import run_pages  # noqa: E402
from pipeline.config import DEFAULT_CONFIG, PipelineConfig, StageSpec  # noqa: E402

__all__ = ["run_pages", "PipelineConfig", "StageSpec", "DEFAULT_CONFIG"]
