# Phase 8 — clean baseline + line-segmentation survey

**Status:** in progress · **Created:** 2026-09-30 · **Owner:** —
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

### A1. Land three unmerged branches — ⏳ needs maintainer approval

| Branch | Commits | What it carries |
|---|--:|---|
| `feat/corpus-doc-layer` | 1 | `corpus/ERRATA.md`, `STRUCTURE.md`, `GLOSSARY.md`, `DEFECT_MAP.md`, the `book.*.corrected.md` overlays, pp.453–457 promoted, `docs/andys_notes.md` |
| `kraken-line-seg-review` | 2 | `docs/kraken_line_segmentation.md`, `dev/kraken_segment.py`, the review UI (`dev/kraken_review/`), 17 page reviews |
| `phase2b-tesseract-finetune` | 1 | The Phase 2b verdict in `docs/phase_2_alternatives.md`, `reports/phase2b_tesseract_finetune_results.md`, `build_tesstrain_gt.py`, FT eval reports |

The first two are based on current `main`. `phase2b-tesseract-finetune` is 34 commits
behind `main` and touches `.gitignore`, `predict_lines_tesseract.py` and
`phase_2_alternatives.md`, so expect a small conflict.

**A4, A5 and A6 need A1 first**, because the files they change only exist on these branches.

### A2. Delete stale branches — ⏳ needs maintainer approval

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

### A4. Fix `corpus/ERRATA.md` E2's root cause (after A1)

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

### A5. Phase 2b verdict + Phase 8 addendum (after A1)

The verdict already exists: `docs/phase_2_alternatives.md` → "fine-tuning follow-up
(2026-06-20)", on the unmerged branch. Once it lands, append:

> **Addendum (2026-09-30, Phase 8).** The fine-tuned `hye-grabar` model (built, gate
> passed) was never wired into `pipeline/registry.py`. Also note: this verdict recommended
> TrOCR as the production backend, but the shipped corpus was OCR'd with **zero-shot
> `hye-calfa-n`**, not TrOCR. **No re-OCR will happen until line segmentation is verified**
> (Phases 8–9). OCR engines (`hye-grabar`, `paddle-calfa-tiny`, `hye-open-ocr`, a
> Qwen-VL fine-tune) will be compared on verified lines from *this* book. Both evals above
> come from a different book, so they rank engines but do not describe the corpus.

### A6. Vol II pp.642–643 — ⏳ maintainer decision

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

1. **A1/A2:** approve landing the three branches and deleting the stale ones?
2. **A6:** promote pp.642–643 now, or leave them for the post-Phase-9 re-promote?

## 5. Results

_Filled in as the survey runs._

## 6. Decision log

- **2026-09-30:** Cut Phase 8 down from the full citable-corpus plan to clean-up plus a
  line-segmentation survey. Maintainer's reasoning: the corpus's errors come from a staged
  pipeline, so fix it stage by stage, starting with segmentation. Everything else moved to
  `docs/backlog/` with blockers noted. Phase 9 is human review of the chosen baseline.
- **2026-09-30:** Audit found that the Phase 2b verdict, the corpus doc layer, and all
  kraken tooling exist on unmerged branches. The roadmap's "never recorded" (§3.4) and
  "nothing references kraken" (§3.1) findings were about `main` only.
