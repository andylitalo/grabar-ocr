# Phase 8 line-segmentation survey

Plan and results: `docs/phase_8_line_segmentation_survey.md` (Part B).

Every candidate segments the same 300-DPI render (`dev/kraken_review/data/page_<N>/render.png`)
and writes the review UI's `segmentation.json` shape to `<tool>/data/page_<N>/`. The review UI
scores each tool separately into `<tool>/reviews/`.

| tool | runner | env |
|---|---|---|
| `kraken` | `run_kraken.py` (copies existing geometry) | stdlib |
| `surya` | `run_surya.py` | `.venv-surya` |
| `hyocr-tess` / `hyocr-paddle` | `run_hyocr.py --config tess\|paddle` | `.venv-hyocr` |
| `projection` (control) | `run_projection.py` | repo `.venv` |

All runners default to the 12-page sample (`common.SAMPLE_PAGES`); pass `--pages 453-643`
for a full run.

## Set up the tool venvs (not committed)

```bash
uv venv -p 3.12 dev/lineseg_survey/.venv-surya
VIRTUAL_ENV=dev/lineseg_survey/.venv-surya uv pip install surya-ocr          # tested 0.22.1

git clone https://github.com/calfa-co/hye-open-ocr dev/lineseg_survey/vendor/hye-open-ocr   # tested c59e946
uv venv -p 3.12 dev/lineseg_survey/.venv-hyocr
VIRTUAL_ENV=dev/lineseg_survey/.venv-hyocr uv pip install "./dev/lineseg_survey/vendor/hye-open-ocr[paddle]"
```

`hyocr-tess` uses `ml_vision/tessdata/hye-calfa-n.traineddata` and needs the `tesseract`
binary.

## Review (human scoring)

```bash
uv run python -m dev.kraken_review.app --tool surya --port 8091   # one tool at a time
```

Flag each wrong line: 1 over-segmented, 2 under-segmented, 3 non-text, 4 clips ink,
5 out of reading order. Drag a box for a missed line. Use Initial / Merge / Split where
that is the fix. Leave correct lines untouched: unflagged means correct.

One op per problem, so the effort count stays honest:
- **Drop-cap left out of its line:** Initial tool (`I`). Box the letter; it attaches to
  the upper line on its right (check the connector). Do not *also* flag that line 4.
- **Clips ink (4)** is for polygons that cut ordinary letters (ascenders, descenders,
  line ends), not for a missing drop-cap.

Edits autosave. When a page is done, press **Mark reviewed**: the page locks (✓ in the
header and the page list) and becomes read-only. **Resume editing** unlocks it.
`score.py` counts only locked pages, so a page that needed no fixes must still be marked.

## Tally and triage

```bash
python3 dev/lineseg_survey/score.py                   # §5 results table from the reviews
dev/lineseg_survey/.venv-surya/bin/python dev/lineseg_survey/overlay.py 453-642 \
    --tools kraken,surya,hyocr-paddle,hyocr-tess,projection --scale 0.3   # side-by-side PNGs
```

## Phase 9 baseline (`paddle-filled`)

```bash
.venv/bin/python dev/lineseg_survey/ensemble.py -v                         # score the fill on the sample reviews
.venv/bin/python dev/lineseg_survey/ensemble.py --write --pages 453-643     # write paddle-filled
```

The non-text filter (ornament bands, speckle) needs numpy + OpenCV, so use the repo
`.venv`. Dropped fills are kept per page as `filtered_fills`. `--no-filter` turns it off
and runs on the stdlib `python3`.
