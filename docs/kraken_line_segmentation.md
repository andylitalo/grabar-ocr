# Kraken line segmentation — findings & migration plan

*Status: FINDINGS + STEP 1 + STEP 2 BUILT. Recorded 2026-07-23, extended 2026-07-24.*
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

## Step 2 — three annotation fixes (2026-07-24)

Reviewing real pages surfaced three recurring kraken errors the flag-only UI couldn't *fix*.
Step 2 makes the review pass produce **corrected geometry**, not just error flags — via one
automated heuristic plus manual editing tools. Corrections are stored as declarative ops
layered on kraken's immutable `lines`, so the raw output is preserved and every edit is
auditable. New review-JSON fields (all backward-compatible; older reviews load with them empty):

```jsonc
"initials":  [ {"id","key":"Ա","box":[x1,y1,x2,y2],"target_line_id":"line_039"} ],
"merges":    [ {"id","line_ids":["line_012","line_013"]} ],
"splits":    [ {"id","line_id":"line_045","at_x":1096.0} ],
"section_titles": [ {"id","key":"Ս","box":[x1,y1,x2,y2],"source_line_id":"line_019"} ]
```

**1. Oversized initials (drop-caps).** Kraken variously splits an oversized first letter into
its own box, mis-attaches it, or misses it. **UI tool (`i`):** box the letter, optionally type
it; it auto-assigns to the **upper of the lines adjacent to the right** and is subtracted from
any other line it overlaps (`target = target ∪ box`, `others = other − box`), so the ink is
never duplicated. Not automated — too varied to trust a heuristic.

**2. Two-column top line merged across the gutter.** Automated in `dev/kraken_segment.py`
(`_post_process`, logged under a new `post_processing` key), **precision-first**. The book's
two-column pages are separated by a printed vertical rule ("‖"); we find it as the longest
contiguous vertical ink run near page center (reliable — even/odd pages mirror the margin, so
`rule_x ≈ 1150` on recto, `≈ 1010` on verso), then split a line only when it straddles the rule
with column-width extent on both sides, the line immediately below is itself two-column, and a
real column boundary — **rule ink flanked by blank on both sides** — sits inside it. That last
test is the key discriminator: a genuine full-width title's central word-gap is pure whitespace
(no rule ink), so titles like "ԵՕԹՆԵՐԵԱԿ ՀՈՈՎՄԱՅԵՅԻՈՑ N." are left intact. A manual **Split**
tool (`s`: click a line, click the cut x) backs it up. **Merge** (`m`) rejoins any wrongly-split
lines.

**Test (validated against all 191 sampled pages' geometry + renders, no re-run of kraken):**
78 splits across 78 pages, ~one running-header per two-column page. Spot-checked ~20 cases:
merged headers (e.g. p494/p460/p457-line5) split exactly at the "‖"; full-width titles
(p457-line2, p562, p607-line59, p610) correctly skipped. Two acceptable misses — bottom-of-page
footers (no row below) and headers whose right column opens with a drop-cap butting the rule —
are covered by the manual Split tool.

**3. Titular section letters (e.g. Ս).** These key the book's later sections. **UI tool (`t`):**
box (or click) the letter and type it; stored as `{key, box, source_line_id}` for later
`key → section-text` structuring.

The review UI (`dev/kraken_review/static/`) gained a tool selector (Flag / Initial / Merge /
Split / Title), a shared letter-input modal, on-canvas rendering of every op, and a side-panel
op list with per-item delete; undo covers all op types. `–-force`-regenerating segmentation
renumbers line ids on the 78 split pages, so re-review those pages after regeneration.

## Out of scope (explicit next steps)

- **Consuming the corrections downstream** — apply `initials`/`merges`/`splits`/`section_titles`
  (and category-3 non-text, `missed_lines`) when cropping/ordering. `missed_lines` still need a
  synthesized baseline merged via `polygonal_reading_order`; splits/merges/initials rewrite line
  geometry; `section_titles` feed section structure. Deferred to pipeline integration.
- **Acting on categories 1/2** beyond the new merge/split/initial tools (e.g. re-segmentation).
- **Productionizing kraken** — add `kraken`/`pypdfium2` to `pyproject.toml`/`uv.lock` and a
  kraken slicer entry in `pipeline/registry.py` (the registry deliberately keeps the slice slot
  open for "a future segmenter (e.g. learned line detection)").

## Decision log

- **2026-07-23:** After a 9-page manual comparison, chose to migrate line segmentation from the
  projection slicer to kraken, **gated on a human review pass**. Built Step 1 (review + record
  only): findings doc, geometry dump, review UI with the 1/2/3 taxonomy. Kept kraken isolated in
  the dev venv until the review validates it. Next: decide how to act on 1/2 and wire 3 downstream.
- **2026-07-24:** Built Step 2 after review surfaced three recurring errors: a precision-first
  automated gutter-split (rule-anchored, validated on 191 pages — 0 false splits in spot-checks),
  and UI tools for drop-cap initials (box + auto-assign-right + subtract), section-title letters
  (box + key), and manual merge/split. Corrections stored as declarative ops; consuming them
  downstream is deferred to pipeline integration.
