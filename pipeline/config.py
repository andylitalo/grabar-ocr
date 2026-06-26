"""
Pipeline configuration: the four swappable stages and the run-folder naming.

A run of the digitization pipeline is fully described by four choices — one per
stage (crop / slice / OCR / correct) — plus optional per-stage params. The chosen
implementation keys index the dispatch tables in ``pipeline.registry``; their short
slugs concatenate into the run-folder name, so the folder *is* a record of how the
text was produced (see ``PipelineConfig.slug``).

This module imports nothing from ``registry`` to avoid a cycle; slug lookup is done
lazily inside ``slug()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageSpec:
    """A single stage's selected implementation + its params.

    ``impl`` is a key into the matching registry table (CROPPERS, SLICERS,
    OCR_ENGINES, CORRECTORS). ``params`` are forwarded to that stage's adapter,
    e.g. the corrector takes ``{"cli_model": ..., "mode": ...}``.
    """

    impl: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineConfig:
    """The four stages that define one digitization approach."""

    crop: StageSpec
    slice: StageSpec
    ocr: StageSpec
    correct: StageSpec

    def slug(self) -> str:
        """Run-folder name derived from each stage's registry slug, e.g.
        ``auto__proj__trocr500__gemini-min``. Imported lazily to avoid a cycle."""
        from pipeline.registry import CORRECTORS, CROPPERS, OCR_ENGINES, SLICERS

        return "__".join(
            [
                CROPPERS[self.crop.impl].slug,
                SLICERS[self.slice.impl].slug,
                OCR_ENGINES[self.ocr.impl].slug,
                CORRECTORS[self.correct.impl].slug,
            ]
        )


# The validated Phase-5 default: headless two-column auto-slice, projection line
# segmentation, fine-tuned TrOCR (scale_500), Gemini minimal-edit correction.
DEFAULT_CONFIG = PipelineConfig(
    crop=StageSpec("auto"),
    slice=StageSpec("projection"),
    ocr=StageSpec("trocr-scale500"),
    correct=StageSpec("gemini-minimal-edit"),
)
