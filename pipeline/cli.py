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
from pipeline.registry import CORRECTORS, CROPPERS, OCR_ENGINES, SLICERS, TRANSLATORS


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
    ap.add_argument("--translate", default="none", choices=list(TRANSLATORS),
                    help="Translate each page to English (default: none)")
    ap.add_argument("--force", action="store_true", help="Re-run stages even if outputs exist")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="Pages processed in parallel (API-bound stages overlap; default 1)")
    args = ap.parse_args()

    pages = _parse_pages(args)
    config = PipelineConfig(
        crop=StageSpec(args.crop),
        slice=StageSpec(args.slice),
        ocr=StageSpec(args.ocr),
        correct=StageSpec(args.correct),
    )
    print(f"Pipeline [{config.slug()}] over pages {pages}"
          f"{f' + translate:{args.translate}' if args.translate != 'none' else ''}"
          f"{f' (concurrency={args.concurrency})' if args.concurrency > 1 else ''}\n")
    res = run_pages(pages, config, translate=args.translate, force=args.force,
                    concurrency=args.concurrency)

    print(f"\nRun dir : {res['run_dir']}")
    print(f"Merged  : {res['merged_doc']}")
    if res["per_page"]:
        print("Pages   :")
        for page_id, path in res["per_page"].items():
            print(f"  {page_id} -> {path}")
    if res["translations"]:
        print(f"\nTranslations [{args.translate}]:")
        for n, path in res["translations"].items():
            print(f"  page_{n} -> {path}")
        print(f"  combined : {res['translated_doc']}")
        print(f"  cost     : ${res['translation_cost']:.4f} total")
    if res["deferred"]:
        print("\nDeferred (need manual annotation):")
        for d in res["deferred"]:
            print(f"  {d['page_id']}: {d['reason']}")
    if res["failed"]:
        print("\nFailed (isolated errors — batch continued):")
        for f in res["failed"]:
            print(f"  {f.get('page_id', f.get('n'))} ({f.get('stage', '')}): {f.get('reason', '')}")
    if res["scorecard"]:
        print(f"\nScorecard: {res['scorecard']}  (overall CER {res['overall_cer']})")
    if res["needs_labeling"]:
        print("\n⚠ No ground truth — CER not scored. To enable scoring:")
        for msg in res["needs_labeling"]:
            print(f"  • {msg}")
    if res["worklist"]:
        print(f"\nWorklist: {res['worklist']}  (see docs/human_completion_guide.md)")

    # ── Summary ──────────────────────────────────────────────────────────────
    digitized = len(res["per_page"])
    translated = len(res["translations"])
    deferred = len(res["deferred"])
    failed = len(res["failed"])
    cost = res["translation_cost"] or 0.0
    print(
        f"\nSummary: digitized {digitized}/{len(pages)} · translated {translated} · "
        f"deferred {deferred} · failed {failed} · cost ${cost:.4f}"
    )

    if res["credit_exhausted"]:
        stop = res["stopped_at"]
        print(
            f"\n{'⛔' * 1} Gemini credits exhausted at page {stop} — refill, then re-run "
            f"the SAME command (idempotent, resumes where it stopped)."
        )


if __name__ == "__main__":
    main()
