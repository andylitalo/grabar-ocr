# Grabar OCR — Project Guide for Coding Agents

## Project Goal
Digitize the Classical Armenian (Grabar) **Տօնացոյց**, pp.453–643 (Bolorgir type, two
volumes), from page scans into a line-by-line, citable text with an English translation.
Every line keeps a stable id and its place on the page, so `armenian-lectionary` can cite
entries by reference.

## Architecture in One Paragraph
Everything runs locally on a Mac; LLM correction and translation are paid API calls. The
first corpus (`corpus/`) was made by `pipeline/`: projection line slicing → Tesseract
(`hye-calfa-n`) → Gemini correction → Gemini translation. The rebuild starts from
human-verified line boxes (`dev/line_review/`, `data/verified_lines/`), reads them with
the Calfa engines (`hye-calfa-n`, `paddle-calfa-tiny`) and corrects them with Gemini 3.1
Pro v4 (`dev/ocr_eval/`). The book-wide run's outputs will live in GCS, and contributors
will correct them in a hosted labeler (`docs/phase_12_hosted_labeler.md`).

## Gated-Phase Development Model
All implementation is guided by phase documents in `docs/` (version-controlled — shared planning + findings). Each phase has a measurable **gate condition**. We do not write code for Phase N+1 until Phase N's gate is passed and its findings are recorded in the phase doc.

This matters because early phases test assumptions (e.g., "does off-the-shelf TrOCR work at all on Bolorgir?"). If an assumption fails, the next phase changes — often significantly. Building ahead of validation wastes effort and obscures where the real problem is.

**Current phase docs** (all phases: `docs/phase_*.md`; the staged order: `docs/backlog/README.md`):
- `docs/phase_9_line_segmentation_review.md` — **review done, gate passed 2026-11-23**; "After the gate" steps 1–3 done (#30), step 4 (recompute the strata) next
- `docs/phase_11_ocr_comparison.md` — **decided, paused**: Calfa engines + Gemini 3.1 Pro v4 correction chosen (95.0% error-free on 160 typed lines, re-scored 2026-11-13); next is the book-wide OCR run after the layout review ("Where this stands"). One Gemini 4 check (`gemini-4-argon`, 2026-10-14) wasn't adopted; a corrector comparison (the other Gemini 4 models; Opus 5.5 also with images of every line and from images alone; GPT 6.2 Sol) is planned, to pick one model per maker for a consensus first pass
- `docs/phase_10_ocr_test_set.md` — deferred until the layout review is done
- `docs/phase_8_line_segmentation_survey.md` — done: the `paddle-filled` line baseline
- `docs/phase_12_hosted_labeler.md` — **planned, not built**: contributors correct the book-wide OCR at `ocr.andylitalo.com`; starts after the region-keyed migration and the book-wide run

**Workflow:** read the current phase doc before touching any code. Update the doc with findings before moving on.

## Repository Layout
```
corpus/             Productionized deliverable: the digitized + translated book,
                    per-page md + per-line json + manifest (committed). Built from the
                    blessed runs by `python -m pipeline.promote` (see corpus/README.md).
pipeline/           The pipeline that made corpus/: modular crop→slice→ocr→correct→
                    translate orchestrator (see pipeline/README.md). Outputs to
                    runs/<config-slug>/ (gitignored scratch).
dev/line_review/    Phase 9 review UI: fix and verify line boxes, mint line ids, transcribe,
                    `migrate repair`
dev/lineseg_survey/ Phase 8 segmenter runners and scoring
dev/ocr_eval/       Phase 10–11 engine runners, ceiling sample, LLM corrector, scoring
dev/kraken_review/  The older review UI that dev/line_review grew from
data_prep/          Pre-processing: PDF → pages → column crops → line crops
ml_vision/          TrOCR / Tesseract fine-tuning, evaluation, LLM-correction scripts
labeling_ui/        FastAPI app for human region-labeling / ground-truth (the crop=human path)
docs/               Phase planning docs + recorded findings (version-controlled)
data/               Data, apart from code: committed ground truth and outputs (column boxes,
                    blank markers, line-seg survey + reviews in data/lineseg_survey/, verified
                    lines, transcriptions, OCR predictions); PDFs, renders and crops stay ignored
reports/            Committed scores and result write-ups
tests/              pytest suite (`uv run pytest`)
```

## Key Conventions
- Python 3.11+; type-annotate all function signatures; `pathlib.Path` over `os.path`
- Secrets (API keys) go in a gitignored `.env` — never in code or git
- GPU device selection via `CUDA_VISIBLE_DEVICES` env var — no hardcoded device indices
- All training runs log to Weights & Biases; evaluation reports CER via `jiwer`

## Data storage
**Rule of thumb:** if a person wrote it, or it's small and stable, it goes in git. If a script
made it and it's big or will be remade, it goes outside git with a manifest.

- **In git:** ground truth and curated data: transcriptions, column boxes, blank markers,
  verified lines, survey reviews. Also small derived outputs that are expensive or can't be
  remade, such as nondeterministic, paid Gemini runs on the test set (`data/ocr_predictions/`,
  ~9 MB). Summary scores go in `reports/`.
- **Never in git:** PDFs, page renders, column and line crops (already ignored in
  `.gitignore`).
- **Machine-written files that are committed** get a `linguist-generated` entry in
  `.gitattributes`, so PR diffs stay reviewable. Add a pattern whenever a new committed
  output directory appears.
- **Separate PRs for code and data.** When a change produces large machine-written data
  (more than ~1,000 lines or ~1 MB of files marked `linguist-generated`), split it in two:
  1. **Code PR**, targeting `main`: the scripts, tests, docs and reports (summary scores),
     plus any small hand-made data. This is the PR that gets a real review.
  2. **Data PR**, stacked on the code PR: only the regenerated outputs. Its description
     says how to rebuild them: the exact command, and the code commit (SHA) it was run
     from. Review it for spot checks and size, not line by line.

  Merge the code PR first. Then retarget the data PR to `main` **before** deleting the
  code branch, because deleting the base branch closes the stacked PR. If the data is
  small, or a code change and its outputs only make sense together (for example a test
  fixture), one PR is fine.
- **Committed machine-written data is diff-friendly text.** Write one record per line: a
  short header, then one compact JSON object per line, or nested lists such as polygons
  written inline instead of one number per line. Never gzip or commit binary formats: git
  can't store compact deltas between versions of them, and nobody can review them.
  - **Frozen, hash-pinned data keeps its exact bytes.** That includes the `paddle-filled`
    baseline (`baseline_sha256.json`) and the frozen Phase 4 sets. Don't reformat or
    regenerate them, even for a format-only change. The rule applies to new outputs, and
    to rewrites a reproduce test checks (e.g. `data/verified_lines/` via
    `rewrite_verified.py` and `test_verified_lines_reproduce`).
  - **Format changes only.** Rounding coordinates or dropping fields that can be
    recomputed changes the data itself. Do that only when designing a new format, after
    checking that nothing downstream reads those fields.
- **Planned: the book-wide OCR run (after the Phase 9 layout review).** Its outputs, the full
  book times every engine and prompt version, go in GCS and are tracked with DVC (or GCS
  plus a committed manifest of path, sha256, settings and date), **not** committed to git.
  Rewriting large files on every iteration is what bloats history, and removing them later
  means rewriting history. Set this up before that run starts.
- **Planned: answers move to a private repo (at the region-keyed migration).** This repo is
  public, and the hosted labeler (`docs/phase_12_hosted_labeler.md`) reuses typed lines as
  hidden gold. The ceiling and test-set transcriptions, and later the gold lines and practice
  keys, move to `grabar-ocr-private` at step 4b of `docs/backlog/region_keyed_data.md`. Until
  then they stay here: `migrate repair` rewrites them during the layout review. Don't move
  them earlier. Once moved, never commit answer files to this repo.
