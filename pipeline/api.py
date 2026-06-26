"""
The pipeline's programmatic entrypoint: submit page numbers, get text.

``run_pages`` is the single stable seam a UI / HTTP layer can import later without
touching the orchestration internals. It returns plain JSON-able data (paths +
the merged text), not framework objects.
"""

from __future__ import annotations

from pipeline.config import DEFAULT_CONFIG, PipelineConfig
from pipeline.orchestrator import run


def run_pages(
    pages: list[int],
    config: PipelineConfig | None = None,
    *,
    force: bool = False,
) -> dict:
    """Run the full crop → slice → OCR → correct pipeline over ``pages``.

    Returns ``{run_dir, config_slug, merged_doc, merged_text, scorecard,
    overall_cer, needs_labeling, deferred, per_page}``. ``merged_text`` is the
    combined document (all text lines, all pages) ready for downstream translation.
    """
    cfg = config or DEFAULT_CONFIG
    result = run(pages, cfg, force=force)
    merged_text = result.merged_doc.read_text(encoding="utf-8") if result.merged_doc else ""
    overall_cer = (
        round(sum(s["cer"] * s["n_scored"] for s in result.scores)
              / sum(s["n_scored"] for s in result.scores), 4)
        if result.scores else None
    )
    return {
        "run_dir": str(result.run_dir),
        "config_slug": cfg.slug(),
        "merged_doc": str(result.merged_doc) if result.merged_doc else None,
        "merged_text": merged_text,
        "scorecard": str(result.scorecard) if result.scorecard else None,
        "overall_cer": overall_cer,
        "needs_labeling": result.needs_labeling,
        "deferred": result.deferred,
        "per_page": {k: str(v) for k, v in result.per_page.items()},
    }
