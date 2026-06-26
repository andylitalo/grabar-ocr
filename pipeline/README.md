# `pipeline/` — modular digitization pipeline

Page numbers in → Grabar text out. A thin orchestration layer that chains four
**swappable** stages over the project's existing, tested stage functions:

| Stage | What it does | Default impl | Lives in |
| --- | --- | --- | --- |
| **crop** | deskew + detect columns + crop | `auto` | `data_prep.auto_slice` |
| **slice** | column → line crops | `projection` | `data_prep.line_cropper` (runs inside crop) |
| **ocr** | line image → text | `trocr-scale500` | `ml_vision/scripts/predict_lines.py` (`.venv_ml`) |
| **correct** | whole-page LLM fix | `gemini-minimal-edit` | `ml_vision/scripts/digitize_page.py` |

OCR is the only stage that runs in the **`.venv_ml`** interpreter (it needs torch);
the orchestrator launches it as a subprocess. Everything else runs in the base
`.venv`. The base process never imports torch.

## Run it

```bash
# default approach (auto / projection / trocr-scale500 / gemini-minimal-edit)
.venv/bin/python -m pipeline.cli --pages 486,487

# swap stages to compare approaches
.venv/bin/python -m pipeline.cli --pages 486,487 --ocr tesseract --correct none
.venv/bin/python -m pipeline.cli --range 486-490 --correct opus-rewrite

# re-run from scratch (ignore cached OCR/correction outputs)
.venv/bin/python -m pipeline.cli --pages 486 --force
```

Or programmatically:

```python
from pipeline import run_pages
out = run_pages([486, 487])
print(out["merged_text"])      # combined document for translation
```

## Output — `runs/<config-slug>/` (gitignored)

The folder name encodes the four choices, e.g.
`runs/auto__proj__trocr500__gemini-min/`:

```
run.json                     resolved config + per-stage docs + tags + status
pages/<page_id>.lines.json   per-line: ocr_beam, corrected, (ref, cer if scored)
merged.md                    all text lines, all pages — feed to a translation LLM
scorecard.json / .md         ONLY when a page has human ground truth
```

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
```
