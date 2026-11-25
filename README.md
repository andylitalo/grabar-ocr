# Grabar OCR

Digitizing a Classical Armenian (Grabar) liturgical book, the **Տօնացոյց** (Tōnatsʻoytsʻ,
pp.453–643, two volumes, Bolorgir type), from page scans into a line-by-line, citable text
with an English translation. Everything runs locally on a Mac, with paid LLM calls for
correction and translation.

## Where things stand (2026-11-25)

**1. A first corpus has shipped.** [`corpus/`](corpus/README.md) holds all 191 pages
(184 with text, 7 blank) as Grabar plus English, page by page and line by line. It was made
by the local [`pipeline/`](pipeline/README.md): projection line slicing → Tesseract
(Calfa's `hye-calfa-n`) → Gemini 3.1 Pro minimal-edit correction → Gemini 3.5 Flash
translation. It is a draft. Its lines are not yet stable or citable, and the known defects
are in [`corpus/ERRATA.md`](corpus/ERRATA.md).

**2. Now: rebuilding it on verified lines.** The order is set in
[`docs/backlog/README.md`](docs/backlog/README.md): verified lines → OCR → correction →
entries that [`armenian-lectionary`](https://github.com/andylitalo/armenian-lectionary)
can cite.

| phase | what | status |
|---|---|---|
| [8](docs/phase_8_line_segmentation_survey.md) | line-segmentation survey | done: the `paddle-filled` baseline |
| [9](docs/phase_9_line_segmentation_review.md) | human review of every line box | review done, gate passed 2026-11-23; "After the gate" steps 1–3 done (#30: retyped lines, v4 + rule 96.3% on 163, not yet committed as a report), step 4 (recompute the strata) next |
| [10](docs/phase_10_ocr_test_set.md) | blank-typed OCR test set | built; deferred, Phase 11 chose on the ceiling sample instead |
| [11](docs/phase_11_ocr_comparison.md) | OCR engine + corrector choice | decided: `hye-calfa-n` + `paddle-calfa-tiny` → Gemini 3.1 Pro **v4** → `՚ի` rule, **95.0%** of 160 typed lines error-free ([report](reports/phase11_ceiling.md)); a corrector comparison for a consensus first pass is planned in PR #29 |
| [12](docs/phase_12_hosted_labeler.md) | hosted labeler at `ocr.andylitalo.com` | planned, not built; the infrastructure smoke test passed |

Next, in order:

1. Finish Phase 9's "After the gate" steps, then mark the Vol I season headings.
2. Move the data to region keys ([`docs/backlog/region_keyed_data.md`](docs/backlog/region_keyed_data.md)).
   This moves the typed answers to a private repo, and the book-wide run's outputs go to
   GCS rather than git.
3. Run the chosen OCR and correction over the whole book.
4. Contributors correct it in the hosted labeler. The target is 99.9% of lines correct.
5. Build sections, entries and dates ([`docs/backlog/book_structure.md`](docs/backlog/book_structure.md)).

Phases 0–7 (TrOCR and Tesseract fine-tuning, LLM post-correction, column detection, vision
correction) were tested on another book, *Ժամագիրք Ատենի*. Their docs are in `docs/` and
their results are in `reports/`.

## How the work is run

The work is split into **gated phases**. Each phase has a doc in `docs/phase_*.md` with a
measurable gate, and the next phase starts only after the gate passes and the findings are
written down. Read the current phase doc before changing code. [`AGENTS.md`](AGENTS.md) has
the conventions, including the data-storage rules: what goes in git, separate code and data
PRs, and diff-friendly formats.

## Repository layout

```
corpus/          the shipped book: per-page md + per-line json + manifest, and hand-kept
                 STRUCTURE / GLOSSARY / ERRATA / TYPOS docs (corpus/README.md)
pipeline/        the pipeline that made corpus/: crop → slice → ocr → correct → translate,
                 with swappable stages (pipeline/README.md)
dev/
  line_review/     Phase 9 review UI: fix and verify line boxes, mint stable line ids,
                   type transcriptions, `migrate repair`
  lineseg_survey/  Phase 8 segmenter runners and scoring
  ocr_eval/        Phase 10–11 engine runners, ceiling sample, LLM corrector, scoring
  kraken_review/   the older review UI that line_review grew from
data/            committed ground truth and small outputs: column boxes, blank markers,
                 survey reviews, verified lines, transcriptions, OCR predictions
                 (data/README.md). PDFs, renders and crops are gitignored.
data_prep/       PDF → page renders → columns → line crops (Phases 0–6)
labeling_ui/     FastAPI app for drawing regions and labeling lines (the "human" crop path)
ml_vision/       TrOCR / Tesseract fine-tuning and LLM-correction scripts (Phases 1–5)
docs/            phase plans and findings, backlog/, labeler/ (contributor agreement, privacy note)
reports/         committed scores and result write-ups
tests/           pytest suite
```

## Setup

Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev                       # base env (.venv): pipeline, review UIs, LLM clients
uv run pytest                             # runs tests/

# heavy ML env (torch, transformers, Tesseract runners), only for OCR and training
uv venv .venv_ml --python 3.11 && uv pip install --python .venv_ml ".[ml]"
```

Some engines have their own environments: `dev/lineseg_survey/.venv-hyocr` (Paddle,
`hye-open-ocr`), `dev/lineseg_survey/.venv-surya` and `dev/ocr_eval/.venv-mlx`. See the
READMEs in `dev/lineseg_survey/` and `dev/ocr_eval/`. API keys (`GEMINI_API_KEY`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) go in a gitignored `.env`.

Source PDFs, page renders and crops are not in git. Tests that need them are skipped
when they're missing.

## Common commands

```bash
uv run python -m dev.line_review.app            # Phase 9 review UI, http://127.0.0.1:8092
uv run python -m dev.line_review.migrate repair # move typed lines onto verified ids
uv run python -m dev.ocr_eval.score             # re-score the Phase 11 engines and correctors
.venv/bin/python -m pipeline.cli --pages 486    # run the original pipeline on a page
.venv/bin/python -m pipeline.promote --range 453-643   # rebuild corpus/ from the pipeline runs
```

## License

- **Code:** Apache License 2.0 — see [`LICENSE`](LICENSE).
- **`corpus/`** (the digitized text, corrections and translation): **CC BY-NC 4.0** — see
  [`corpus/LICENSE`](corpus/LICENSE). The OCR was produced with Calfa's models
  (`hye-calfa-n`, and from Phase 11 also `paddle-calfa-tiny` and `hye-open-ocr` line
  layout), all CC BY-NC 4.0; credit Calfa when reusing it. `corpus/LICENSE` lists every
  model in the chain.
- **Committed engine outputs and transcriptions** (`data/ocr_predictions/`,
  `data/transcriptions/`): **CC BY-NC 4.0**, same terms as the corpus — see the
  `LICENSE` in each directory.
- Short OCR excerpts quoted as evidence in `docs/` and `reports/` are under the same
  terms as the corpus.
