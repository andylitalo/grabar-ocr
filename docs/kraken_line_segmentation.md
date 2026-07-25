# Kraken line segmentation — findings & migration plan

*Status: FINDINGS + STEP 1 BUILT. Recorded 2026-07-23.*
*Companion to `docs/slice_categorization_findings_and_next_steps.md` (which diagnosed the
shipping slicer's failures) and `docs/ocr_approach_comparison.md` (the OCR-engine comparison —
this doc covers the orthogonal **line-segmentation** axis).*

## TL;DR

Kraken neural **baseline** segmentation (`blla.segment`) qualitatively beats the shipping
horizontal-projection slicer on the 9 hardest pages sampled from *Ժամագիրք Ատենի*. It filters
non-text natively, keeps oversized section-opening initials with their line, segments lines in a
**single step** (no compounding crop→slice errors), and generalizes past evenly-spaced
two-column block text. It still makes mistakes, so the migration is **gated on a human review
pass** — for which Step 1 (this build) provides the doc, a geometry-dump step, and a review UI
that lets a human click each segmentation and categorize errors as
**1 = over-segmentation, 2 = under-segmentation, 3 = non-text**, saving them to JSON.

## Why change — the shipping slicer's limits

The production path is `data_prep/auto_slice.py` → `data_prep/column_detector.py` →
`data_prep/line_cropper.py` (horizontal-projection line slicing). Its documented weaknesses:

- **Block-text assumption.** It assumes a deskewed, rule-framed, evenly-spaced two-column body.
  `column_detector.detect_columns` **defers** anything else, so single-column bands, title pages,
  and tables are never sliced (`docs/phase_6_column_detection.md`).
- **Over-segmentation of drop-caps / ornaments** and chopped-glyph specks that read as empty
  lines (`docs/slice_categorization_findings_and_next_steps.md`).
- **Under-segmentation** — bridging diacritics / tight leading fuse two lines into one crop; the
  only catastrophic (whole-line-drop) class, patched with the `_split_oversized_run` median
  guard (`docs/phase_5_lineslice_and_llm_correction.md`).
- **Compounding errors.** crop → slice is two geometric stages; a slightly off crop propagates
  into every downstream line. A post-hoc `data_prep/line_filter.py` band-aid exists solely to
  drop the non-text crops the slicer emits.

## How kraken differs

| | Shipping (projection) | Kraken (`blla.segment`) |
|---|---|---|
| Method | Classical CV: per-row dark-pixel projection, trough splits | Neural baseline detection (`blla.mlmodel`) |
| Line shape | Axis-aligned bounding box | Polygon (`line.boundary`) + baseline |
| Stages | crop → slice (2 stages, compounding) | single-step page → lines |
| Non-text | needs `line_filter.py` post-hoc | filtered natively by the model |
| Big initials | over-split / chopped | kept with the line |
| Layout scope | deskewed two-column block only (else deferred) | generalizes to titles/tables/single-col |
| Deps | `data_prep/` (in-tree) | `kraken` (dev venv only, not in pyproject) |

## Sample pages (all 9 segmented; line counts from kraken)

| page | content | kraken lines |
|------|---------|-------------:|
| 448 | Two-column, decorative divider, mixed fonts | 70 |
| 530 | Illustration with Bible verse | 58 |
| 546 | Two columns, decorative separator, small font | 89 |
| 551 | blank | 31 |
| 552 | Title page (many fonts, decorations, illustration) | 4 |
| 555 | Title, subtitle, two-column text | 81 |
| 557 | Large decorative header, title, taregir | 59 |
| 564 | Taregir mid-page | 69 |
| 641 | Great Paschal Cycle Table | 199 |

(Line counts equal the per-line JPEG counts from the original run in `dev/segmented_lines/`.
Some pages — e.g. the decorative header on 530 and the near-blank 551 — carry a handful of
spurious boxes over ornaments; those are exactly the errors the review UI is built to catch.)

## Error taxonomy (formalized here)

Prior docs described these families qualitatively; the review UI codes them numerically:

1. **over-segmentation** — one real line split into several (specks, chopped initials).
2. **under-segmentation** — several real lines merged into one polygon.
3. **non-text** — a segmentation over an ornament/divider/illustration/margin mark; downstream
   should ignore these. (This is the positive class of the existing non-character convention.)

## Step 1 — what was built (this branch)

- **Geometry dump** — `dev/kraken_segment.py` runs kraken (dev venv) on the 9 pages and writes,
  per page, `dev/kraken_review/data/page_<N>/{render.png, segmentation.json}`. The JSON carries
  each line's `boundary` polygon, `baseline`, and `bbox`. Kraken lives only in
  `dev/venv-grabar/`, so this is the sole kraken-importing step.
- **Review UI** — `dev/kraken_review/` (standalone FastAPI app; **no kraken import**), modeled on
  `labeling_ui/`: a Canvas overlays the polygons on `render.png`; clicking a segmentation opens a
  modal to pick 1/2/3 (button or keypress); flags persist to
  `dev/kraken_review/reviews/page_<N>.review.json`. Lines absent from `flags` are implicitly
  correct; category-3 lines are the ones to ignore downstream. **Dragging** a box marks a line
  kraken missed entirely (saved to `missed_lines` as `{id, box:[x1,y1,x2,y2]}`); click a box to
  delete it.

### Reading order (and where missed lines slot in)

Kraken orders its output in reading order natively: `blla.segment`'s default `reading_order_fn`
is `kraken.lib.segmentation.polygonal_reading_order`, a pure-geometry topological sort over the
line baselines/polygons (handles multi-column). So `segmentation.json`'s `line_001..N` is already
reading order. `polygonal_reading_order(lines, text_direction='lr')` orders *any* list of
baseline-bearing lines, so a human-drawn missed box is merged in later by synthesizing a baseline
(the box's horizontal midline) and re-running the whole set through it — producing one unified
order for kraken lines + missed boxes. That merge belongs to the pipeline-integration step; the
UI only captures box geometry.

Run:
```bash
dev/venv-grabar/bin/python dev/kraken_segment.py     # generate geometry (kraken)
uv run python -m dev.kraken_review.app               # review UI on :8090
```

## Out of scope (explicit next steps)

- **Acting on categories 1/2** — a fix/re-segmentation workflow (unknown; deferred by the user).
- **Wiring category-3 non-text into downstream** filtering.
- **Consuming `missed_lines`** — synthesize a baseline per box, merge into reading order via
  `polygonal_reading_order`, and either crop raw or re-segment within the box.
- **Productionizing kraken** — add `kraken`/`pypdfium2` to `pyproject.toml`/`uv.lock` and a
  kraken slicer entry in `pipeline/registry.py` (the registry deliberately keeps the slice slot
  open for "a future segmenter (e.g. learned line detection)").

## Decision log

- **2026-07-23:** After a 9-page manual comparison, chose to migrate line segmentation from the
  projection slicer to kraken, **gated on a human review pass**. Built Step 1 (review + record
  only): findings doc, geometry dump, review UI with the 1/2/3 taxonomy. Kept kraken isolated in
  the dev venv until the review validates it. Next: decide how to act on 1/2 and wire 3 downstream.
