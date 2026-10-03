# Phase 8 — clean baseline + line-segmentation survey

**Status:** complete (gate passed 2026-10-02) · **Created:** 2026-09-30 · **Owner:** —
**Supersedes:** the broader "citable corpus" plan, now in
[`docs/backlog/citable_corpus_roadmap.md`](backlog/citable_corpus_roadmap.md). The deferred
items and what blocks each one are indexed in [`docs/backlog/README.md`](backlog/README.md).
**Next:** Phase 9, [`docs/phase_9_line_segmentation_review.md`](phase_9_line_segmentation_review.md).

## 1. Scope

Two deliverables:

- **A.** A clean repo: unmerged work landed, stale branches gone, untracked artifacts
  ignored, and known doc errors fixed. Phase 9 should start without surprises.
- **B.** A survey of line-segmentation tools on this book, ending in **one chosen baseline
  segmenter**. Phase 9 then puts that baseline in front of a human for review and correction.

**Out of scope:** OCR, correction, entries, citations, re-promoting the corpus, and the
normalizer. All of these are in the backlog.

### Why line segmentation comes first

The corpus's known errors (roadmap §3.2) trace back to one staged pipeline:
crop → slice → OCR → correct. Each stage inherits the errors of the one before it. The fix
is to rebuild it in order, making each stage solid before starting the next:

1. **Segment lines** and verify them by human review (Phases 8–9).
2. **Enumerate** pages, lines and sections so every line has a stable id and can be cited.
3. **OCR** the verified lines, comparing engines against ground truth from this book.
4. **Correct**, then enumerate **entries** and link each entry to its lines.

The consumer-facing citation will be `volume → section → page → entry` plus a content hash.
Every entry keeps a link to its line ids, so any citation can bring up the original scan
lines. Line ids can only be stable if the geometry under them is verified. Everything
depends on this phase and the next.

---

## 2. Part A — repo clean-up

Audit of 2026-09-30. Several items the roadmap listed as "gaps" were finished work sitting
on branches that were never merged.

### A1. Land three unmerged branches — ✅ merged 2026-09-30

| Branch | Commits | What it carries |
|---|--:|---|
| `feat/corpus-doc-layer` | 1 | `corpus/ERRATA.md`, `STRUCTURE.md`, `GLOSSARY.md`, `DEFECT_MAP.md`, the `book.*.corrected.md` overlays, pp.453–457 promoted, `docs/andys_notes.md` |
| `kraken-line-seg-review` | 2 | `docs/kraken_line_segmentation.md`, `dev/kraken_segment.py`, the review UI (`dev/kraken_review/`), 17 page reviews |
| `phase2b-tesseract-finetune` | 1 | The Phase 2b verdict in `docs/phase_2_alternatives.md`, `reports/phase2b_tesseract_finetune_results.md`, `build_tesstrain_gt.py`, FT eval reports |

The first two are based on current `main`. Conflicts were in `.gitignore` (kraken and Phase 8 ignore rules combined) and
`predict_lines_tesseract.py`, where Phase 2b's `--lang` flag was combined with the later
Armenian character whitelist. Both are kept.

**A4, A5 and A6 need A1 first**, because the files they change only exist on these branches.

### A2. Delete stale branches — ✅ approved 2026-09-30

These are fully merged into `main` and carry nothing unique: `feat/book-run`,
`feat/label-and-translate-ui`, `feat/modular-pipeline`, `feat/translation-stage`,
`phase3-4-honest-finetuning` (plus `origin/phase3-4-honest-finetuning`).
`exp/gemini-thinking-budget` has 3 unmerged commits, but its files are byte-identical on
`main` (it was squash-merged as `66b8c8f`).

### A3. Ignore untracked artifacts — ✅ `.gitignore` updated 2026-09-30

| Path | Size | What it is |
|---|--:|---|
| `dev/venv-grabar/` | 1.0 GB | kraken dev venv (`.gitignore` matches `venv/`, not `venv-grabar/`) |
| `dev/kraken_review/data/` | 221 MB | kraken geometry + page renders. Can be regenerated, but slowly |
| `dev/segmented_lines/`, `dev/extracted_lines/` | 34 MB | kraken per-line crops from the first 9-page run |
| `ml_vision/tessdata_ft/` | 254 MB | tesstrain scratch from Phase 2b |

Also untracked: `reports/nonchar_garble_gate.html`, which `ERRATA.md` E2 cites (commit it
or leave it as a regenerable report), and `reports/phase4_newpage_page_0400_human.{csv,html}`.

### A4. Fix `corpus/ERRATA.md` E2's root cause — ✅ applied 2026-09-30

E2 says the corpus was transcribed "with **baseline `tesseract`**". It was transcribed
with Tesseract running Calfa's **`hye-calfa-n`** historical-Armenian traineddata, zero-shot
(`pipeline/registry.py` `OCR_ENGINES["tesseract"]`; `LANG = "hye-calfa-n"` in
`ml_vision/scripts/predict_lines_tesseract.py`). The `tag: "tesseract"` in run configs is a
label, not a model name. Replacement for E2's first sentence under "Root cause":

> **Root cause is OCR quality.** The corpus was transcribed with Tesseract running Calfa's
> **`hye-calfa-n`** traineddata (Classical/Western/Eastern Armenian, including historical
> fonts), zero-shot. It is not baseline Tesseract; the run-config `tag: "tesseract"` is a
> label. On the *Ժամագիրք Ատենի* evaluation sets it scores 4.9% (frozen) / 4.6%
> (page_0400) line CER (`docs/phase_2_alternatives.md`). That is a different book, so this
> corpus has no measured CER yet. Even so, it (a) hallucinates on no-text slices and
> (b) mangles display and heading text.

The rest of E2 stays as written. The TrOCR comparison is still accurate.

### A5. Phase 2b verdict + Phase 8 addendum — ✅ applied 2026-09-30

The verdict already exists: `docs/phase_2_alternatives.md` → "fine-tuning follow-up
(2026-06-20)", on the unmerged branch. Once it lands, append:

> **Addendum (2026-09-30, Phase 8).** The fine-tuned `hye-grabar` model (built, gate
> passed) was never wired into `pipeline/registry.py`. Also note: this verdict recommended
> TrOCR as the production backend, but the shipped corpus was OCR'd with **zero-shot
> `hye-calfa-n`**, not TrOCR. **No re-OCR will happen until line segmentation is verified**
> (Phases 8–9). OCR engines (`hye-grabar`, `paddle-calfa-tiny`, `hye-open-ocr`, a
> Qwen-VL fine-tune) will be compared on verified lines from *this* book. Both evals above
> come from a different book, so they rank engines but do not describe the corpus.

### A6. Vol II pp.642–643 — ✅ promoted 2026-09-30

These two pages are the **colophon** of the 1915 Jerusalem printing. p.642 is the
Յիշատակարան ("Memorial": the fourth Jerusalem printing of the Ժամագիրք and Տօնացոյց, in
two volumes, the Ատենի and Ձեռաց editions). p.643 is an editorial note: the taregir lists of
Volume II were set as plain prose instead of tables and columns, and merged saint-feasts
were separated. They were OCR'd, corrected and translated in
`runs/human__proj__tess__gemini-min/`, but `corpus/` was promoted with `--range 453-641`.
"Promotion" means running `python -m pipeline.promote --range 453-643` so they appear in
`corpus/` and the coverage notes in `STRUCTURE.md` / `ERRATA.md` can be closed.

The pages have no liturgical content, but the colophon is the book's own provenance
statement. Recommendation: promote after A1, as the last clean-up step. Their OCR is as
flawed as the rest of the corpus and will be redone after Phase 9 anyway.

### A7. Deferred, with reasons (moved to the backlog)

- **Phase 7 vision correction.** Not built. Kept as an option after the OCR engine choice.
- **`docs/ocr_approach_comparison.md`.** Its CER cells need transcription ground truth,
  which needs verified lines.
- **ERRATA backlog.** `ERRATA.md`'s "Candidate defects" section is a themed list from a
  QA pass: garble, cut-offs, column bleed, column swaps, inconsistent terms, and untranslated
  Armenian. It is waiting for page-by-page adjudication, where the maintainer confirms each
  defect against the scan and approves the fix that goes into the `*.corrected.md` overlays
  (see ERRATA's "Workflow"). **It is frozen.** Almost every item is an OCR or segmentation
  defect that Phases 8–9 and the re-OCR will change, so hand-patching now would be thrown
  away. What remains afterwards comes back as a much shorter list.
- **Roadmap §3.2 token/garble errors.** Resolved long-term by verified segmentation plus a
  better OCR engine, not by patching.

---

## 3. Part B — line-segmentation survey

**Question:** which segmenter gives the fewest human corrections per page on *this* book?
That tool becomes Phase 9's baseline. The survey needs a winner, not a leaderboard.

### B1. Candidates

| Candidate | Why it's here | Known facts / caveats |
|---|---|---|
| **kraken** `blla.segment` (incumbent) | Already run on 195 pages (448–642). Review UI, rule-anchored gutter split, and 17 reviewed pages exist | Polygons + baselines + reading order. Apache-2.0. Errors seen so far: drop-caps, gutter-crossing headers, ornaments (`kraken_line_segmentation.md`) |
| **Surya** (Datalab) detection + layout + reading order | Strongest general-purpose open line detector with Armenian listed | Polygons + confidence. Code Apache-2.0; weights modified RAIL-M. Datalab's Marker is built on Surya, so Surya covers "Datalab". Check whether Datalab's newer models expose line-level geometry |
| **`hye-open-ocr` layout stage** (Calfa) | Armenian-specific. Its pipeline is also the likely OCR baseline later | Layout via DocLayout-YOLO or PP-DocLayoutV3, output ALTO. **To verify:** whether it produces its own line geometry or relies on Tesseract's layout analysis inside regions. CC BY-NC |
| **LlamaIndex / LlamaParse** | Raised by the maintainer | **Unverified.** A hosted, paid parsing API built for LLM ingestion. Desk check only: include it only if it returns per-line polygons and is not closed-API-only |
| **Projection slicer** (shipping, `data_prep/`) | The control. Any winner must clearly beat it | Axis-aligned boxes. Known failures in `slice_categorization_findings_and_next_steps.md` |

**Optional if time allows:** PaddleOCR's script-agnostic text detector (DB). Calfa's
`hye-paddle` is recognition-only, so this detector would be its natural partner.

#### Desk-check outcome (2026-09-30)

| Candidate | Line geometry | Reading order | Verdict |
|---|---|---|---|
| kraken | polygon + baseline | native (`polygonal_reading_order`) | **run** (geometry already exists) |
| Surya 0.22.1 | 4-point polygon + confidence, no baseline | none from the detector. The layout/reading-order models are now VLM-based and need vllm or llama.cpp. The non-VLM `fast_layout` (rf-detr) gives ordered blocks, and lines are ordered by block | **run** as `surya` |
| `hye-open-ocr` | **no line detector of its own**: "the layout stage only finds regions; line and word segmentation is left to the recognizer" (README) | X-Y cut over regions | **run twice**: `hyocr-tess` (DocLayout-YOLO + Tesseract `--psm 4` lines, axis-aligned boxes) and `hyocr-paddle` (PP-DocLayoutV3 + PaddleOCR DB detection, quad polygons). The second covers the optional Paddle detector |
| LlamaParse | line-level **axis-aligned boxes** in a JSONL sidecar (`granular_bboxes`), PDF points | n/a | **dropped**: closed, paid hosted API with no polygons. Its open sibling LiteParse segments scans with bundled Tesseract, so `hyocr-tess` already covers that behaviour |
| Projection slicer | full-width boxes per region | region order | **run** as the control, on the shared render (no deskew). A page the detector isn't confident on is recorded as deferred with zero lines |

### B2. Method

1. **Desk check** (no runs). For each candidate: output shape (polygon? baseline? reading
   order?), install cost, CPU/GPU, licence. Drop anything that can't emit per-line
   geometry.
2. **Common format.** Convert every survivor's output into kraken-review's
   `segmentation.json` shape (`boundary`, `baseline`, `bbox`, ordered `line_NNN`). The
   existing review UI can then display and score all of them. Phase 9 reads the same format,
   so this adapter is not throwaway work.
3. **Sample of ~12 pages**, stratified across the book's hard cases: title/display (453),
   two-column body with running header (457, 519), merged-column debris (488),
   illustration (530), Vol II decorative header + taregir (557, 564), leap-pair taregir
   (593), full-width titles (610), the Paschal table (641), the colophon (642), plus one
   clean Vol II laydown page.
4. **Human scoring** in the review UI, one page at a time, all candidates. Count per page:
   over-segmentation, under-segmentation, non-text boxes, missed lines, wrong reading
   order, and polygons that clip ink (ascenders/descenders, drop-caps). The 17 existing
   kraken reviews only score kraken's own output, so they cannot be the answer key. They
   are a head start on kraken's column.
5. **Pick** the candidate with the lowest **correction effort per page** (roughly total
   ops a reviewer needs). Prefer the simpler install on a near-tie.

### B3. Gate

- Every surviving candidate has per-category error counts on the same ~12 pages, in a
  table in §5 below.
- One baseline is chosen, and the reason is written into the decision log.
- The chosen tool has been run on **all content pages 453–643**, and its output is in the
  common format, ready for Phase 9.

---

## 4. Open questions for the maintainer

1. **Human-scoring scope (§5.1):** score only kraken, Surya and hyocr-paddle, and keep
   p.641 out of the effort totals?

A1, A2 and A6 were approved 2026-09-30. The ERRATA candidate list is out of scope from here on.

## 5. Results

Tooling: `dev/lineseg_survey/` (see its README). Every tool segments the same kraken
render, writes the review UI's `segmentation.json` shape, and is scored in its own review
dir (`python -m dev.kraken_review.app --tool <tool>`). Two flag categories were added for
the survey: **4 clips ink** and **5 out of reading order**. `score.py` turns the reviews into
the table below.

### 5.1 Automated triage (2026-09-30, before human scoring)

Lines emitted per page:

| page | content | kraken | surya | hyocr-paddle | hyocr-tess | projection |
|---:|---|--:|--:|--:|--:|--:|
| 453 | title page | 26 | 25 | 15 | 24 | 26 |
| 457 | two-col + header | 69 | 66 | 66 | 50 | 71 |
| 488 | column debris | 92 | 84 | 91 | 53 | 95 |
| 519 | Vol I body | 92 | 91 | 91 | 88 | 96 |
| 530 | illustration | 58 | 13 | 2 | 2 | 1 |
| 557 | Vol II header + taregir | 59 | 51 | 53 | 49 | 0 (deferred) |
| 564 | taregir mid-page | 69 | 59 | 67 | 45 | 0 (deferred) |
| 575 | Vol II laydown | 77 | 77 | 79 | 77 | 79 |
| 593 | leap-pair taregir | 86 | 85 | 86 | 95 | 86 |
| 610 | full-width titles | 74 | 73 | 75 | 73 | 0 (deferred) |
| 641 | Paschal table | 199 | 571 | 583 | 15 | 112 |
| 642 | colophon | 28 | 28 | 28 | 22 | 29 |

Side-by-side overlays of pp.453, 457, 488, 530, 557, 564 and 641 (`overlay.py`) show:

- **kraken** finds every text line, including display type and the taregir letter on
  p.557. Its main cost is **non-text boxes on ornaments**: about 56 on p.530's border, and
  a handful on every decorative header (457, 557).
- **Surya** is clean on body text and mostly ignores ornaments. But it **missed the
  taregir letter Ա on p.557**, the letter that keys a Vol II section. It merges adjacent
  lines in some Vol II rubrics (p.564 top-left) and clips the title on p.453.
- **hyocr-paddle** is the cleanest on body text and on the illustration page (exactly the
  2 caption lines on p.530), and it caught the taregir letter on p.557. But it **dropped
  11 of 26 lines on the title page** (p.453), and missed lines cost the most to fix.
- **All three** missed the taregir letter Դ on p.564; only hyocr-tess boxed it. Phase 9's
  section-title tool will be needed whichever tool wins.
- **hyocr-tess** misses whole lines (p.457 right column; 53 vs ~92 on p.488) and draws
  boxes across the gutter (p.564).
- **projection** defers 3 of 12 pages (557, 564, 610), which in production meant a human
  crop, and boxes the whole of p.530 as one line.
- **p.641 (Paschal table)** is segmented at cell level by Surya and Paddle, and at a mix of
  cell and row level by kraken. Line counts there mean little. The table is already
  transcribed as a CSV (`corpus/STRUCTURE.md`).

**Proposed:** drop `hyocr-tess` and `projection` from human scoring. Both are clearly
beaten, and scoring them would add ~24 page reviews for no decision value. Score
**kraken, Surya and hyocr-paddle** on the 11 sample pages other than 641; review 641 on
its own for whichever tool wins.

### 5.2 Human scoring

Scope approved 2026-09-30: kraken, Surya and hyocr-paddle. **p.641 (Paschal table) is out
of scoring for every tool** (maintainer, 2026-09-30): kraken's errors there were too many
to review, no tool segments it as lines, and it is already hand-transcribed as a CSV.
`score.py` skips it. "Effort" is ops per page
(`score.py`): each flag category, missed box, initial, merge and split counts 1.

**Surya: reviewed 2026-09-30, all 12 pages.**

| page | lines | over | under | non-text | clips | order | missed | initials | merges | splits | effort |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 453 | 25 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 2 |
| 457 | 66 | 0 | 5 | 0 | 20 | 0 | 0 | 4 | 0 | 0 | 29 |
| 488 | 84 | 0 | 11 | 0 | 8 | 9 | 0 | 4 | 0 | 9 | 41 |
| 519 | 91 | 0 | 5 | 0 | 28 | 1 | 0 | 7 | 0 | 1 | 42 |
| 530 | 13 | 0 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 10 |
| 557 | 51 | 0 | 1 | 0 | 18 | 0 | 0 | 1 | 0 | 0 | 20 |
| 564 | 59 | 0 | 2 | 0 | 15 | 1 | 0 | 1 | 0 | 0 | 19 |
| 575 | 77 | 0 | 1 | 0 | 20 | 0 | 0 | 1 | 0 | 0 | 22 |
| 593 | 85 | 0 | 1 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 13 |
| 610 | 73 | 0 | 2 | 0 | 6 | 0 | 0 | 1 | 0 | 0 | 9 |
| 642 | 28 | 0 | 1 | 0 | 10 | 0 | 0 | 5 | 0 | 0 | 16 |
| **11 pages** | **652** | **0** | **29** | **11** | **138** | **11** | **0** | **24** | **0** | **10** | **223** |
| 641 (table, not scored) | 571 | 2 | 11 | 0 | 0 | 0 | 5 | 0 | 1 | 8 | 27 |

- **Effort: 223 over 11 pages = 20.3 per page.**
- **Clips ink is 62% of it** (138 of 223), and it is systematic: Surya's boxes are tight
  rectangles that shave ascenders and descenders. A uniform vertical pad, which is a code
  fix rather than reviewer work, cures most of it (`clip_padding.py`): 6 px → 102/138,
  **8 px → 114/138 (83%)**, 10 px → 117/138. With an 8 px pad counted as free, effort
  drops to **109 over 11 pages ≈ 9.9 per page**. This is an estimate: where lines are too
  tightly spaced for a blank row between them, the measure can't separate descender
  from neighbour.
- **What remains is real:** 29 under-segmentations (11 on p.488), 24 drop-cap initials
  left outside their lines, 11 reading-order errors (9 on p.488), 10 ornament boxes on
  p.530, and 10 splits on p.488.
- No missed lines outside the table, and no over-segmentation.

The same pad will be applied to kraken and hyocr-paddle before comparing.

**kraken: reviewed 2026-09-30, 11 pages.**

| page | lines | over | under | non-text | clips | order | missed | initials | merges | splits | effort |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 453 | 26 | 0 | 1 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 5 |
| 457 | 69 | 0 | 1 | 2 | 2 | 1 | 0 | 1 | 0 | 0 | 7 |
| 488 | 92 | 0 | 2 | 0 | 5 | 2 | 0 | 0 | 0 | 0 | 9 |
| 519 | 92 | 0 | 2 | 0 | 6 | 1 | 0 | 1 | 0 | 0 | 10 |
| 530 | 58 | 0 | 0 | 56 | 0 | 0 | 0 | 0 | 0 | 0 | 56 |
| 557 | 59 | 3 | 1 | 5 | 1 | 0 | 1 | 1 | 0 | 0 | 12 |
| 564 | 69 | 0 | 2 | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 5 |
| 575 | 77 | 0 | 3 | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 7 |
| 593 | 86 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 610 | 74 | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 2 |
| 642 | 28 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 3 |
| **11 pages** | **730** | **3** | **15** | **67** | **20** | **5** | **1** | **5** | **0** | **1** | **117** |

- **Effort: 117 over 11 pages = 10.6 per page**, about half of Surya's 20.3.
- **The 8 px pad helps kraken little:** 7 of 20 clip flags (its polygons already follow
  the ink). Padded effort is 110, **10.0 per page**, against Surya's ~9.9.
- **56 of the 117 are ornament boxes on one page (p.530).** In practice that is one
  "Mark blank" click (every box on the page is non-text). Without p.530, kraken is
  **61 over 10 pages = 6.1 per page** (padded 5.4), against Surya's 21.3 raw / ~9.9 padded
  on the same 10 pages.
- Outside p.530, kraken beats Surya in every category: under-segmentation 15 vs 29,
  drop-caps left out 5 vs 24, reading order 5 vs 11, splits 1 vs 10, and only 1 missed
  line. Its weak spot is ornaments on decorative pages (p.557: 5 non-text, 3 over).

**hyocr-paddle: reviewed 2026-09-30, 11 pages.**

| page | lines | over | under | non-text | clips | order | missed | initials | merges | splits | effort |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 453 | 15 | 0 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 0 | 9 |
| 457 | 66 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 2 |
| 488 | 91 | 0 | 1 | 0 | 1 | 0 | 2 | 1 | 0 | 0 | 5 |
| 519 | 91 | 1 | 1 | 0 | 5 | 0 | 1 | 2 | 0 | 0 | 10 |
| 530 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 557 | 53 | 2 | 1 | 0 | 0 | 0 | 1 | 1 | 1 | 0 | 6 |
| 564 | 67 | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 2 |
| 575 | 79 | 3 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 0 | 5 |
| 593 | 86 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 610 | 75 | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 4 |
| 642 | 28 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| **11 pages** | **653** | **8** | **7** | **0** | **7** | **0** | **15** | **5** | **3** | **0** | **45** |

- **Effort: 45 over 11 pages = 4.1 per page.** The 8 px pad cures only 2 of its 7 clip
  flags (padded: 3.9 per page).
- **Zero non-text boxes and zero reading-order errors.** The layout stage drops figures
  and ornaments before line detection, which is why p.530 is clean. The X-Y-cut region
  order held on every page.
- **Its weakness is missed lines: 15, 9 of them on the title page (p.453).** A missed
  line is the riskiest error, because text silently disappears if no one draws the box.
  Outside p.453 it missed 6 lines across 10 pages.

### 5.3 Comparison

| tool | ops / page (raw) | with 8 px pad free | without p.530 |
|---|--:|--:|--:|
| **hyocr-paddle** | **4.1** | **3.9** | **4.5** |
| kraken | 10.6 | 10.0 | 6.1 |
| Surya | 20.3 | ~9.9 | ~9.9 |

hyocr-paddle needs the fewest corrections under every adjustment. Its missed lines are
the one error class where it trails kraken (15 vs 1), and they cluster on the display-type
title page. Phase 9 must make missed lines easy to spot, e.g. by highlighting ink that no
line covers.

### 5.4 Filling Paddle's missed lines from kraken + Surya (maintainer's proposal)

Rule (`ensemble.py`): add a kraken line when Surya **agrees** on it (bbox IoU ≥ *agree*)
and **no Paddle line covers it** (Paddle boxes cover < 30% of it). The kraken polygon is
used because Surya's rectangles clip ink. Scored against the 15 lines the reviewer boxed
as missed in Paddle's review (p.641 excluded):

| agree ≥ | missed lines recovered | lines added | false adds |
|--:|--:|--:|--:|
| 0.3 | 15/15 | 18 | 3 |
| **0.4** | **15/15** | **17** | **2** |
| 0.5–0.6 | 14/15 | 15 | 1 |
| 0.7 | 10/15 | 10 | 0 |

The coverage threshold (0.2–0.5) made no difference. The one line lost at 0.5 is p.575's
printed page number "571" in the running header: Surya's box there is much wider than
kraken's. **Chosen: agree ≥ 0.4.** A false add costs one non-text flag; a missed line
risks silently losing text.

Projected Paddle effort with filling: 45 − 15 missed + 2 false adds = **32 over 11 pages
≈ 2.9 per page**. Caveat: the threshold was chosen on the same 11 pages it is scored on.
The plateau from 0.4 to 0.6 suggests it isn't overfit.

Filled lines are slotted into Paddle's reading order after the nearest Paddle line above
them in the same column, and tagged `"source": "kraken-fill"` so Phase 9 can show them.
On p.453 all 10 filled title lines came out in correct order. The result is written as
tool **`paddle-filled`**, the proposed Phase 9 baseline.

Taregir title letters (e.g. Դ on p.564) are missed by all three tools. The reviewer boxes
them with the section-title tool in Phase 9 regardless, since that box is what marks the
section.

### 5.5 Non-text filter for filled lines (2026-10-01)

Once hyocr-paddle had run on 104 pages (453–549 plus the sample), the fill rule proposed
**136 lines on 64 pages**. Checked by eye against the scan (not yet Phase 9-reviewed),
**123 are real lines and 13 are not.** The real ones are:

- **Lines opening with a large capital** (Զ, Տ, Ս, Պ…), on almost every body page.
  Paddle's DB detector skips them; the line is inside a layout region.
- **Runs of a column that no layout region covers**: 12 lines on p.490, 6 on p.491, 9 on
  p.531. This is a layout-stage miss, which a detector setting or fine-tune would not fix.
- **Running-header page numbers** ("(482)").

The 13 non-text fills are border/woodcut bands (8 on the illustration pages 456, 482, 496,
502, 514 ×2, 522, 530; 2 on p.545), the rule ornament on p.453, and 2 speckle-noise boxes in
p.520's bottom margin.

Box shape doesn't separate them: the bands have title-line aspect ratios (~11) and
display-type heights (1.9–2.8× the median line). Ink texture does
(`ensemble.nontext_reason`):

| measure (inside the box) | real lines (123) | non-text (13) | cutoff |
|---|---|---|---|
| share of pixel columns with no ink | ≥ 0.11 (median 0.26) | 10 of 13 ≤ 0.03 | drop if < 0.05 (`ornament`) |
| share of ink blobs < 20 px | ≤ 0.26 | the other 3: 0.65–0.86 | drop if > 0.5 (`speckle`) |

**Result: 13 of 13 non-text fills dropped, 0 of 123 real lines lost.** On the reviewed
sample: 15/15 missed lines still recovered, false adds 2 → 0, so projected effort is
**30 over 11 pages ≈ 2.7 per page**. Both cutoffs sit at least 2× from the nearest real
line, but they were fitted on the pages they're scored on, and Vol II (pp.550–640) hasn't
been checked yet. The filter only touches fills, never Paddle's own lines. Dropped boxes are
kept in `segmentation.json` as `filtered_fills` with the reason.

**Full run (2026-10-02, pp.453–643):** 172 lines filled, 15 non-text fills dropped
(the 13 above plus a vine band and a rule ornament on p.551). The first full run also
dropped the running-header page numbers on pp.617 and 643: kraken's box there takes in
the "—(" and ")—" dashes, and a horizontal rule leaves no ink-free column. Fix: remove
horizontal runs longer than 1.5 box heights before counting blank columns
(`RULE_LEN`). After the fix, every kept fill has ≥ 0.10 blank columns and every ornament
≤ 0.03. Six pages have no lines and are blank in the scan (455, 481, 501, 521, 529, 552).

**Agree lowered to 0.3 (maintainer, 2026-10-02).** With the filter in place, the 0.3 row of
§5.4 no longer costs a false add on the sample: p.530's extra candidate (the INRI plaque
inside the woodcut) is dropped as an ornament, so the sample still shows 15/15 recovered
and 0 false adds. Over the book, 0.3 adds 7 lines to the 0.4 run, 6 of them real (three
page numbers, p.462's large-capital line, p.554's display-title words, p.624's rubric line).
The seventh is a rule ornament on p.553 that the filter misses. It also drops 6 more
non-text candidates (ornament bands, a grape cluster, p.530's INRI, speckle on blank
p.521). The baseline is now **agree ≥ 0.3**: 179 filled lines, 21 dropped.

### 5.6 Lower DB `box_thresh` for large-capital lines? No (2026-10-01)

Tried before the full run: can Paddle's detector find the large-capital lines itself, if
it keeps lower-scoring boxes? `ARMENIAN_OCR_PADDLE_DET_BOX_THRESH` at 0.5 / 0.4 / 0.3 (the
PaddleOCR default is 0.6), on pp.453, 457, 488, 519, 557, written as tools
`hyocr-paddle-bt<X>` (`run_hyocr.py --tool`) and compared with the Paddle reviews:

| box_thresh | body-line misses recovered | other misses (p.453 title, p.557 header) | original lines lost | new unmatched boxes |
|---:|---:|---:|---:|---:|
| 0.5 | 3/4 | 0/10 | 0 | 3 |
| 0.4 | **4/4** | 0/10 | 0 | 4 |
| 0.3 | 4/4 | 0/10 | 0 | 4 |

- At 0.4 Paddle finds every large-capital line it missed in the sample (457, 488 ×2, 519)
  and loses nothing.
- The new unmatched boxes are noise: three slivers 6–21 px tall inside existing lines or on
  a dot (p.488 ×2, p.519; Paddle's real lines are ≥ 35 px), and a box around p.557's drop
  cap Ե as its own line.
- The title-page and header misses don't move: those lines sit outside any layout region,
  so the detector never sees them.

**Decision: keep the default 0.6.** The kraken+Surya fill already recovers all 4 of these
lines (§5.4), so on `paddle-filled` lowering the threshold saves nothing and adds about 1
noise box per page. It becomes the right lever only if the fill's kraken/Surya inputs are
dropped, e.g. to make the tool Paddle-only for other books. In that case use 0.4 plus a
minimum line height (≈ 0.5× the page's median).

## 6. Decision log

- **2026-09-30:** Cut Phase 8 down from the full citable-corpus plan to clean-up plus a
  line-segmentation survey. Maintainer's reasoning: the corpus's errors come from a staged
  pipeline, so fix it stage by stage, starting with segmentation. Everything else moved to
  `docs/backlog/` with blockers noted. Phase 9 is human review of the chosen baseline.
- **2026-09-30:** Audit found that the Phase 2b verdict, the corpus doc layer, and all
  kraken tooling exist on unmerged branches. The roadmap's "never recorded" (§3.4) and
  "nothing references kraken" (§3.1) findings were about `main` only.
- **2026-09-30:** Part A done. Merged the three branches, fixed ERRATA E2, appended the
  Phase 2b addendum, and promoted pp.453–643 (additive: only pp.642–643 changed). Deleted the
  stale branches. The ERRATA candidate list is frozen and out of scope. Next: Part B.
- **2026-09-30:** Part B started on `feat/line-seg-survey`. Desk check dropped LlamaParse
  (closed API, axis-aligned boxes only). Found that `hye-open-ocr` has no line detector,
  so it was run as two candidates (Tesseract lines, Paddle DB detection). Built survey
  runners, a shared geometry format, overlays and a scorer; extended the review UI with
  `--tool`, flag categories 4–5 and a "Mark reviewed" button. All five candidates run on
  the 12-page sample. Automated triage proposes human-scoring three of them (§5.1).
- **2026-09-30: Baseline chosen: `paddle-filled` (agree ≥ 0.4).** hyocr-paddle needed the
  fewest corrections of the three scored tools (4.1 ops/page vs kraken 10.6, Surya 20.3;
  §5.3), with zero non-text boxes and zero reading-order errors. Its one weakness, missed
  lines, is closed by adding kraken lines that Surya agrees on and Paddle lacks (§5.4):
  15/15 missed lines recovered, 2 false adds, ≈2.9 ops/page projected. The reviewer chose
  the rule. p.641 is out of scoring (hand-transcribed CSV).

- **2026-10-01: Non-text filter added to the fill** (§5.5). On 104 pages it dropped 13 of
  13 ornament/speckle fills and no real line; sample projection ≈2.7 ops/page. Lowering
  Paddle's DB `box_thresh` was tried and rejected for this baseline (§5.6): it finds the
  same lines the fill already recovers and adds noise. Fine-tuning (Paddle DB, kraken) is
  kept as a future experiment, not needed for Phase 9.
- **2026-10-02: Phase 8 gate passed.** `paddle-filled` written for all of pp.453–643 (191
  pages, 172 filled lines, 15 non-text fills dropped) in the common `segmentation.json`
  format. The filter now ignores horizontal rules, so page numbers set between dashes
  aren't dropped (§5.5). Next: Phase 9.
- **2026-10-02: fill agreement lowered from 0.4 to 0.3** (§5.5). With the non-text filter,
  0.3 keeps the sample at 15/15 recovered and 0 false adds, and adds 6 real lines (plus 1
  ornament) over the book.
