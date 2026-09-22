# `corpus/` — the productionized digitized + translated book

This is the **canonical, committed deliverable**: the digitized Grabar and English
translation of the Տօնացոյց (Tonatsoyts), pages 458–641, consolidated from the pipeline's
best runs into one page-keyed tree. Other services consume this directory; it is the stable
interface, decoupled from the prototyping runs under `runs/` (which are gitignored scratch).

Everything here is **text only** — no images or PDFs. The heavy raster artifacts (page
renders, region crops, line slices) stay out of git; the files here point at them by
relative repo path for traceability.

> **Understanding the lectionary?** Start with **[`STRUCTURE.md`](STRUCTURE.md)** — the
> master index of the book's two-volume structure, section-to-page map, and the gotchas
> (chiefly: the year-letter is a *Julian* code). Companion hand-maintained docs:
> [`GLOSSARY.md`](GLOSSARY.md) (controlled term renderings), [`ERRATA.md`](ERRATA.md)
> (digitization/translation defects + the `book.*.corrected.md` overlays), and
> [`TYPOS.md`](TYPOS.md) (errors in the printed source). `README.md`, `STRUCTURE.md`,
> `GLOSSARY.md`, `ERRATA.md`, `TYPOS.md`, and `book.*.corrected.md` are **hand-maintained**;
> everything else in this directory is **generated** by `pipeline.promote` — do not edit it.

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

**Blank pages** carry `blank: true`, an empty `lines[]`, `english: null`, and a
`provenance.blank_marker` pointing at the committed `data/pages/blank/page_XXXX.json`.
They are keyed by the base page id (`page_0481`, no `_auto`/`_human`) because blankness is
a property of the source page, not of any crop.

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

## Coverage, blanks & gaps

`manifest.json` records the promoted `pages[]` (each with a `blank` flag), an `n_blank`
count, and a `gaps[]` list. As of the current promotion: **184 of 184 pages** (458–641),
of which **178 are digitized content and 6 are blank** (481, 495, 501, 521, 529, 552), and
**0 gaps**.

**Blank pages** are source pages a human marked in the labeling UI; the marker lives at
`data/pages/blank/page_XXXX.json` (committed) and is the single source of truth, read via
`storage.is_blank(n)`. Both the pipeline (which skips crop/OCR/translate for a blank) and
the promoter consult it, so a blank page is handled explicitly rather than being mistaken
for an "unbalanced column" deferral. This is what previously turned the 6 blanks into
gaps — the marker existed but nothing downstream read it.

A real **gap** is a page with neither content nor a blank marker (e.g. a page the detector
deferred that a human has not yet labeled *or* marked blank). To close a content gap:
annotate its regions in the labeling UI, re-run the pipeline for that page, then re-promote.
To close a blank gap: mark it blank in the labeling UI (or `storage.set_blank(n, True)`)
and re-promote.

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
