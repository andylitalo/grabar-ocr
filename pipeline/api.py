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
    translate: str = "none",
    force: bool = False,
) -> dict:
    """Run the full crop → slice → OCR → correct (→ translate) pipeline over ``pages``.

    ``translate`` selects a TRANSLATORS key ("gemini"/"opus"/"sonnet"/"none"); when
    not "none", each page is also translated into English under
    ``runs/<slug>/translations/<model>/``.

    Returns ``{run_dir, config_slug, merged_doc, merged_text, scorecard,
    overall_cer, needs_labeling, deferred, per_page, translations, translated_doc,
    translation_cost, worklist}``. ``merged_text`` is the combined Grabar document
    (all text lines, all pages).
    """
    cfg = config or DEFAULT_CONFIG
    result = run(pages, cfg, translate=translate, force=force)
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
        "translations": {n: str(p) for n, p in result.translations.items()},
        "translated_doc": str(result.translated_doc) if result.translated_doc else None,
        "translation_cost": round(result.translation_cost, 6) if translate != "none" else None,
        "worklist": str(result.worklist) if result.worklist else None,
    }


def digitize_and_translate(
    pages: list[int],
    *,
    translator: str = "gemini",
    config: PipelineConfig | None = None,
    force: bool = False,
) -> dict:
    """Digitize ``pages`` and translate them to English in one call.

    The single stable seam the future UI imports: page numbers in, English (plus the
    intermediate Grabar) out. Thin convenience wrapper over ``run_pages`` with a
    translator selected by default.
    """
    return run_pages(pages, config, translate=translator, force=force)
