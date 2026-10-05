# Phase 10 — OCR test set from verified lines

**Status:** built 2026-10-04; transcription under way · **Created:** 2026-10-04 · **Owner:** —
**Depends on:** Phase 9's verified lines (`data/verified_lines/`). It runs alongside the
rest of Phase 9's verification and only ever samples from pages already verified.
**Feeds:** the OCR engine comparison (`docs/backlog/README.md`: `hye-calfa-n`, `hye-grabar`,
`paddle-calfa-tiny`, `hye-open-ocr`, a Qwen-VL fine-tune), scored on *this* book.

## Goal

A human-transcribed test set of about **300 lines** from the Տօնացոյց, keyed by stable
line id, so OCR engines can be ranked by CER on this book rather than on *Ժամագիրք Ատենի*
(every CER in the repo so far is from that other book; roadmap §3.2(f)).

## Decisions (maintainer, 2026-10-04)

- **Blank, not pre-filled.** Every line is typed from scratch. Every engine is a candidate,
  and correcting one engine's guess tends to leave its subtle errors in the ground truth.
- **A stratified line sample, not whole pages.** More variety per hour typed.
- **Literal, as printed** (Phase 0 rules): exact characters; pativ abbreviations kept with
  their mark (՟), not expanded; no spelling fixes; punctuation as printed (։ ՝ ՛ ․ « »);
  a line-end hyphen typed as printed (֊). Engines are scored on what is on the page.
- **Its own phase doc** (this one).

## Sample

Strata and quotas (total 300):

| stratum | what | quota |
|---|---|--:|
| `vol1-body` | Vol I (pp.453–551) ordinary lines | 110 |
| `vol2-body` | Vol II (pp.553–643) ordinary lines | 110 |
| `display` | headings and display type: line height ≥ 1.4× the page's median | 50 |
| `drop-cap` | lines carrying an `initial` | 30 |

A line falls in the first matching stratum among `drop-cap`, `display`, then its volume's
`body`. The Paschal table (p.641) is excluded.

**Spread.** At most 2 body lines, 1 display line and 1 drop-cap line per page, so each
stratum follows verification through the book instead of filling its quota from the first
pages verified (a single cap of 4 per page let one stratum crowd out the others).

**Incremental and stable.** The pool is whatever is verified at the time. Each candidate
gets a rank from a hash of a fixed seed and its line id. Running the sampler tops up each
stratum's unfilled quota with the lowest-ranked unpicked lines. Picks are append-only, so
verifying more pages later never moves an existing pick. A picked line whose id is later
retired (re-verification split it, say) is reported, not silently dropped.

**Noise floor.** About 1 in 10 transcribed lines (30 in all, chosen by hash) is queued
for a **blind recheck**: typed again later without seeing the first transcription. The
CER between the two passes is the ground truth's own error rate; engine differences
smaller than it don't count.

## Line images

One crop function, shared by the UI and later by the engine runs, so every engine sees
exactly what the human saw: the line's bbox plus a small pad, with pixels outside the
verified polygon set to white (neighbouring lines' ink can't leak in). The UI also shows
the page around the line for context.

## Storage (committed)

- `data/transcriptions/sample.json`: seed, quotas, and the append-only list of picks
  `{id, stratum, page}`.
- `data/transcriptions/page_<N>.json`: per line id `{text, status, at}` with status
  `done` / `illegible` / `bad-crop`, plus `recheck: {text, at}` for the blind second pass.
  `bad-crop` sends the line back to Phase 9 (its geometry is wrong) rather than into the
  test set.

## UI

A second workflow in the Phase 9 app (`dev/line_review`, at `/transcribe`), modelled on
`labeling_ui`'s label view: the crop large, the page context below, a text box (Enter
submits and advances), **Illegible** and **Bad crop** buttons, Back/Next, a strip of
pills per sampled line, per-stratum progress, and a palette for the characters a standard
Armenian keyboard makes awkward (՟ ֊ ։ ՝ ՛ ․ « »). A recheck mode serves the
blind-recheck queue with the first transcription hidden.

## Build log

- **2026-10-04, built** (in `dev/line_review/`, at `/transcribe`):
  - `transcribe.py`: strata, append-only top-up, per-stratum page caps, the recheck queue,
    and per-task transcription storage. Records carry `by` and `prefill`, so a later task
    where contributors correct OCR predictions reuses them (`task="corrections"`,
    `prefill={engine, text}`) without mixing with the blank-typed test set;
  - `crops.py`: the shared line crop (polygon-masked) and the context view;
  - endpoints in `app.py`, the page in `static/transcribe.{html,js}`;
  - tests: `tests/test_line_review_transcribe.py` (13).

  Found while testing on the 10 verified pages: a single cap of 4 picks per page let
  whichever stratum went first take every page's cap (110 body lines from 8 pages; then
  19 drop-cap vs 4 body with scarce strata first). Fixed with a cap per stratum per page.
  The first top-up gives 32 lines (18 body, 8 display, 6 drop-cap), and Vol II strata
  stay empty until Vol II pages are verified.

  **Follow-up:** lines marked `bad-crop` should show up in line review as pages to fix.

## Gate

- At least 300 sampled lines transcribed (`done` or `illegible`), every stratum at quota.
- The blind recheck is done on its 30 lines, and its CER is recorded here.
- The crops for every test line can be regenerated from `data/verified_lines/` alone.

## Out of scope

Running and scoring the OCR engines (the next step: an eval harness reading
`data/transcriptions/`), normalization or abbreviation expansion, and entries.
