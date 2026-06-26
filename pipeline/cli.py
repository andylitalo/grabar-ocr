"""
CLI for the modular digitization pipeline.

    .venv/bin/python -m pipeline.cli --pages 486,487
    .venv/bin/python -m pipeline.cli --pages 486,487 --ocr tesseract --correct none
    .venv/bin/python -m pipeline.cli --range 486-490 --crop auto --force

Each stage is chosen by its registry key (see pipeline/registry.py). The run lands
in runs/<config-slug>/ with per-line JSON, a merged document, and — when ground
truth exists — a CER scorecard.
"""

from __future__ import annotations

import argparse

from pipeline.api import run_pages
from pipeline.config import PipelineConfig, StageSpec
from pipeline.registry import CORRECTORS, CROPPERS, OCR_ENGINES, SLICERS


def _parse_pages(args: argparse.Namespace) -> list[int]:
    if args.range:
        lo, hi = (int(x) for x in args.range.split("-", 1))
        return list(range(lo, hi + 1))
    if args.pages:
        return [int(x) for x in args.pages.split(",") if x.strip()]
    raise SystemExit("Specify --pages 486,487 or --range 486-490")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pages", help="Comma-separated page numbers, e.g. 486,487")
    g.add_argument("--range", help="Inclusive page range, e.g. 486-490")
    ap.add_argument("--crop", default="auto", choices=list(CROPPERS))
    ap.add_argument("--slice", default="projection", choices=list(SLICERS))
    ap.add_argument("--ocr", default="trocr-scale500", choices=list(OCR_ENGINES))
    ap.add_argument("--correct", default="gemini-minimal-edit", choices=list(CORRECTORS))
    ap.add_argument("--force", action="store_true", help="Re-run stages even if outputs exist")
    args = ap.parse_args()

    pages = _parse_pages(args)
    config = PipelineConfig(
        crop=StageSpec(args.crop),
        slice=StageSpec(args.slice),
        ocr=StageSpec(args.ocr),
        correct=StageSpec(args.correct),
    )
    print(f"Pipeline [{config.slug()}] over pages {pages}\n")
    res = run_pages(pages, config, force=args.force)

    print(f"\nRun dir : {res['run_dir']}")
    print(f"Merged  : {res['merged_doc']}")
    if res["per_page"]:
        print("Pages   :")
        for page_id, path in res["per_page"].items():
            print(f"  {page_id} -> {path}")
    if res["deferred"]:
        print("\nDeferred (need manual annotation):")
        for d in res["deferred"]:
            print(f"  {d['page_id']}: {d['reason']}")
    if res["scorecard"]:
        print(f"\nScorecard: {res['scorecard']}  (overall CER {res['overall_cer']})")
    if res["needs_labeling"]:
        print("\n⚠ No ground truth — CER not scored. To enable scoring:")
        for msg in res["needs_labeling"]:
            print(f"  • {msg}")


if __name__ == "__main__":
    main()
