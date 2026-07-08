# `corpus/` — the productionized digitized + translated book

This is the **canonical, committed deliverable**: the digitized Grabar and English
translation of the Տօնացոյց (Tonatsoyts), pages 458–641, consolidated from the pipeline's
best runs into one page-keyed tree. Other services consume this directory; it is the stable
interface, decoupled from the prototyping runs under `runs/` (which are gitignored scratch).

Everything here is **text only** — no images or PDFs. The heavy raster artifacts (page
renders, region crops, line slices) stay out of git; the files here point at them by
relative repo path for traceability.

## Layout

```
corpus/
  manifest.json              book index: page range, source-run config, per-page rows, gaps
  book.grabar.md             all Grabar, "## <page_id>" headers, ascending page order
  book.english.md            all English, "## <page_id>" headers, ascending page order
  pages/
    page_NNNN.md             per-page: YAML frontmatter + "## Grabar" + "## English"
    page_NNNN.lines.json     per-line Grabar + provenance pointers + page-level English
```

`NNNN` is the user-facing book page number, zero-padded (e.g. `page_0458`).

### `pages/page_NNNN.lines.json`

The per-line record and the machine-readable interface. Top-level keys:

- `page`, `page_id` — the number and the method-tagged id (`page_0458_auto` / `_human`).
- `source` — how the Grabar/English was produced: `run_slug`, `crop`, `slice`,
  `ocr{impl,tag}`, `correct{model,mode}`, `translate{model}`.
- `provenance` — `source_pdf`, `deskew_render`, `region_boxes` (relative repo paths).
- `cer`, `counts` — score (null when no ground truth) and line tallies.
- `english` — the full page translation (prose; see note below).
- `lines[]` — per line: `index`, `line_id`, `region`, `column`, `non_character`,
  `ocr_raw` (raw OCR beam), `grabar` (LLM-corrected final), `region_bbox` (pixel box on
  the deskewed page), `crop_image`, `line_image` (relative repo paths).

**English is per-page, not per-line.** The translator reads the whole page for context, so
there is no line-by-line English; the page prose lives at the top level (`english`) and in
the `## English` section of the markdown.

## Provenance / traceability

Any line traces back through the (local, gitignored) intermediate artifacts. Only the
region-box geometry (`data/columns/boxes/*.json`) is itself committed; the rest is
reproducible on the machine that ran the pipeline:

```
corpus/pages/page_0458.lines.json   line.grabar / line.ocr_raw / line.region_bbox
  └─ line_image  → data/lines/page_0458_auto/region_01_left/line_001.png
  └─ crop_image  → data/columns/page_0458_auto_region_01_left.png
  └─ region_boxes→ data/columns/boxes/page_0458_auto.json      (COMMITTED geometry)
        └─ deskew_render → data/_labeling_work/page_0458/page_deskew.png
              └─ source_pdf → data/pages/458.pdf
```

The `source` block records the exact stage impls and model ids at each hop; the originating
`runs/<run_slug>/run.json` holds the full resolved config.

## Coverage & gaps

`manifest.json` records the promoted `pages[]` and a `gaps[]` list. As of the current
promotion: **178 of 184 pages** (458–641). The 6 gaps (481, 495, 501, 521, 529, 552) are
pages the auto detector deferred (odd/unbalanced columns) and that have no human labels yet
— each carries its deferral reason. To close a gap: annotate its regions in the labeling UI,
re-run the pipeline for that page, then re-promote.

## Regenerate

Promotion is a pure consolidation of existing run artifacts — no stage re-runs, no token
spend. From the repo root:

```bash
.venv/bin/python -m pipeline.promote --range 458-641
```

Defaults: `--from auto__proj__tess__gemini-min human__proj__tess__gemini-min` (applied in
order, so the human-verified run wins on overlapping pages) and `--translator gemini-flash`.
Re-running is content-idempotent (only the manifest `generated` timestamp changes). See
`pipeline/corpus.py` for the logic.
