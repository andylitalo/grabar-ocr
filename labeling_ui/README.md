# labeling_ui — Grabar line-labeling web tool

A small local web app for producing ground-truth labels for Classical Armenian
(Grabar/Bolorgir) OCR. It takes the existing one-page PDFs in `data/pages/`,
lets you crop each page into two columns, auto-segments the columns into line
images, and then walks you through labeling each line. Output is written in the
exact layout the training pipeline already consumes
(`data/lines/page_XXXX/column_Y/line_NNN.{png,txt}`).

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) from the repo root
`pyproject.toml`:

```bash
uv sync
```

## Run

```bash
uv run python -m labeling_ui.app
# or, with autoreload during development:
uv run uvicorn labeling_ui.app:app --reload --port 8080
```

Then open http://127.0.0.1:8080/.

## Workflow

1. **Select a page.** Type a page number (e.g. `335` for `data/pages/335.pdf`)
   or step with **Prev/Next**; **Next unlabeled →** jumps to the next page with
   no labels. Each page shows a status badge: `unlabeled` / `in_progress` /
   `done`. Click **Select this page** to continue.
2. **Crop two columns.** Drag the two suggested boxes over the left and right
   columns (drag a corner to resize, the inside to move). Keep **Deskew
   columns** on unless a page is already straight. Click **Segment lines →**.
   - The selected page is rendered at **300 DPI**; column crops are saved to
     `data/columns/page_XXXX_column_{1,2}.png` and each column is split into
     line PNGs under `data/lines/page_XXXX/column_{1,2}/`.
   - If the page already has labels, segmenting again asks for confirmation
     before discarding them (a guard against clobbering work).
3. **Label each line.** For every line image:
   - Type the Grabar text and press **Enter** to submit and advance.
   - Press **Empty** (Alt+E) for a blank line / section marker — stored as an
     empty `.txt`, kept but skipped at train time.
   - Press **Reject** (Alt+R) for a cut-off or low-quality crop — the image is
     moved to a `rejected/` subdir and excluded from the dataset.
   - Navigate with **Back/Next** (Alt+←/→) or click any pill in the strip to
     jump. Previously entered text is prefilled and re-editable; re-labeling a
     rejected line automatically un-rejects it.
   - The progress readout and pill colors track status; a summary at the end
     warns if any line is still `pending`.

### Keyboard shortcuts (label view)

| Key | Action |
|-----|--------|
| Enter | submit text + advance |
| Shift+Enter | newline in the text box |
| Alt+E | mark empty + advance |
| Alt+R | reject + advance |
| Alt+← / Alt+→ | back / next (no relabel) |
| Esc | blur the text box |

## On-disk conventions

Line status is computed purely from the filesystem (no database):

| State | Files |
|-------|-------|
| labeled | `line_NNN.png` + non-empty `line_NNN.txt` |
| empty | `line_NNN.png` + empty `line_NNN.txt` |
| rejected | `column_Y/rejected/line_NNN.png`, no `.txt` |
| pending | `line_NNN.png`, no `.txt` |

All labels are UTF-8. Restarting the server loses nothing — state is the files.

## Hand-off to training

The tool stops at `data/lines/page_XXXX/column_Y/`. To assemble the flat
training set, use the existing `data_prep/build_phase4_dataset.py` (add new
pages to its `NEW_PAGES`, or generalize it to glob `data/lines/page_*`). The
`rejected/` subdirs hold only PNGs and are invisible to its flatten/glob logic.

## Architecture

- `app.py` — FastAPI HTTP layer (endpoints, static mount). Local dev utility,
  not a model endpoint, so FastAPI is fine (BentoML stays the ML serving layer).
- `pipeline.py` — orchestration over the reused `data_prep` functions
  (`pdf_to_images`, `deskew`, `crop_lines`); renders/crops/segments.
- `storage.py` — filesystem layer: paths, status computation, label mutations.
- `static/` — single-page vanilla-JS frontend (page browser, crop canvas,
  keyboard-driven labeling).
