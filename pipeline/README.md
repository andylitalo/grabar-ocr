# `pipeline/` — modular digitization pipeline

Page numbers in → Grabar text out. A thin orchestration layer that chains four
**swappable** stages over the project's existing, tested stage functions:

| Stage | What it does | Default impl | Lives in |
| --- | --- | --- | --- |
| **crop** | deskew + detect columns + crop | `auto` | `data_prep.auto_slice` |
| **slice** | column → line crops | `projection` | `data_prep.line_cropper` (runs inside crop) |
| **ocr** | line image → text | `trocr-scale500` | `ml_vision/scripts/predict_lines.py` (`.venv_ml`) |
| **correct** | whole-page LLM fix | `gemini-minimal-edit` | `ml_vision/scripts/digitize_page.py` |

Plus an **orthogonal 5th stage**:

| Stage | What it does | Default impl | Lives in |
| --- | --- | --- | --- |
| **translate** | Grabar page → English | `none` | `pipeline/translate.py` |

OCR is the only stage that runs in the **`.venv_ml`** interpreter (it needs torch);
the orchestrator launches it as a subprocess. Everything else runs in the base
`.venv`. The base process never imports torch.

### Why translation is orthogonal, not a 5th slug

The four-stage slug names the **digitize identity** — the run folder records how the
Grabar text was produced. The translator does not change that text; it consumes it.
So a translator is a **run option** (`--translate`), and each model's output lands in
its own subdir, `translations/<model>/`, inside the same run folder. You can translate
one corrected page with gemini, opus, and sonnet side by side — no OCR/correction
recompute, no token re-spend. Translations are cached **next to the Grabar they came
from** (`data/predictions/<correct_tag>/<page_id>/translation_<model>.{txt,json}`), so
re-runs are free unless `--force`.

## Run it

```bash
# default approach (auto / projection / trocr-scale500 / gemini-minimal-edit)
.venv/bin/python -m pipeline.cli --pages 486,487

# swap stages to compare approaches
.venv/bin/python -m pipeline.cli --pages 486,487 --ocr tesseract --correct none
.venv/bin/python -m pipeline.cli --range 486-490 --correct opus-rewrite

# re-run from scratch (ignore cached OCR/correction outputs)
.venv/bin/python -m pipeline.cli --pages 486 --force

# digitize AND translate to English (the final deliverable)
.venv/bin/python -m pipeline.cli --pages 486,487 --translate gemini

# translate the whole book (453–646) — page numbers all the way to English
.venv/bin/python -m pipeline.cli --range 453-646 --translate gemini
```

Or programmatically:

```python
from pipeline import run_pages, digitize_and_translate
out = run_pages([486, 487])                       # Grabar only
print(out["merged_text"])                         # combined Grabar document

out = digitize_and_translate([486, 487])          # Grabar + English (gemini)
print(out["translated_doc"], out["translation_cost"])
```

## Output — `runs/<config-slug>/` (gitignored)

The folder name encodes the four choices, e.g.
`runs/auto__proj__trocr500__gemini-min/`:

```
run.json                          resolved config + per-stage docs + tags + status
pages/<page_id>.lines.json        per-line: ocr_beam, corrected, (ref, cer if scored)
merged.md                         all Grabar text lines, all pages, reading order
scorecard.json / .md              ONLY when a page has human ground truth
needs_human.md                    worklist: deferred pages + pages lacking ground truth
translations/<model>/page_<n>.txt English per page (when --translate ≠ none)
translations/<model>/translated.md combined English doc, ## page_<n> headers
```

`page_<n>` in the translation filenames uses the user-facing page **number**. The
`needs_human.md` worklist lists pages the detector deferred (annotate regions in the
labeling UI before they can be digitized) and digitized pages that still lack a
transcription (label them to enable CER scoring).

## Scoring

CER (jiwer) is computed against human line transcriptions in
`data/lines/<page_id>/<region>/line_NNN.txt`. Pages with **no** transcription
(e.g. auto-sliced 486/487 today) produce text immediately and a clear
"label these N lines" instruction; the scorecard appears automatically once the
lines are labeled in the labeling UI and you re-run the same config.

## Adding a new approach

Add **one** entry to the relevant dict in `registry.py` (CROPPERS / SLICERS /
OCR_ENGINES / CORRECTORS) plus, if needed, a small adapter in `stages.py`. The
orchestrator, CLI, and artifact writers need no changes. Each registry entry's
`slug` becomes part of the run-folder name and its `doc` is recorded in `run.json`,
so every run is self-documenting and comparable side by side.

- A new OCR engine: add `{script, tag}` in its `meta` (it's launched as a `.venv_ml`
  subprocess, schema-identical to `predict_lines.py`).
- A new corrector: bake `{cli_model, mode}` into `meta["params"]`; reuse
  `stages.correct_llm`.
- A new translator: add an entry to `TRANSLATORS` with `{cli_model}` in
  `meta["params"]`; reuse `stages.translate_llm`. Its `slug` becomes the
  `translations/<slug>/` subdir.
```
