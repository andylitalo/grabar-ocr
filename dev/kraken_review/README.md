# Kraken line-segmentation review UI

A minimal standalone tool for reviewing kraken's line segmentations and flagging the ones that
need fixing. Part of Step 1 of migrating line segmentation to kraken — see
`docs/kraken_line_segmentation.md`.

It visualizes kraken's line polygons on top of the page they came from, lets you click a
segmentation that looks wrong, and categorize the error:

- **1 — over-segmentation** (one real line split into pieces)
- **2 — under-segmentation** (several real lines merged into one)
- **3 — non-text** (an ornament / divider / illustration / mark to ignore downstream)

It also lets you mark **lines kraken missed entirely** by dragging a box over them.

Flags are saved per page; unflagged lines are implicitly correct.

## Two steps

### 1. Generate segmentation geometry (needs kraken)

Kraken is installed only in the ad-hoc dev venv (`dev/venv-grabar/`), so run the dump script
with that interpreter. It renders each page and writes, per page,
`dev/kraken_review/data/page_<N>/{render.png, segmentation.json}`:

```bash
# a contiguous range (inclusive):
dev/venv-grabar/bin/python dev/kraken_segment.py --range 448-648

# or explicit pages:
dev/venv-grabar/bin/python dev/kraken_segment.py --pages 448,530,546

# no args = the original 9 test pages
dev/venv-grabar/bin/python dev/kraken_segment.py
```

Already-generated pages are **skipped** (resumable across interruptions — kraken is slow over
hundreds of pages); pass `--force` to regenerate. Missing source PDFs are skipped with a warning.
The model path is set at the top of `dev/kraken_segment.py`.

### 2. Run the review UI (no kraken needed)

The UI only reads the pre-generated JSON + PNG, so it runs under the repo's uv env
(FastAPI/uvicorn/Pillow only — no kraken import):

```bash
uv run python -m dev.kraken_review.app
```

Then open <http://127.0.0.1:8090>.

- Use **Prev/Next** or the page dropdown to move between pages.
- **Click** a segmentation to open the flag modal; pick an option by clicking or pressing
  **1/2/3**. **Esc** or click outside cancels. Re-click a flagged line to change or **clear** it.
- **Drag** a box on the page to mark a line kraken **missed** entirely. Click a drawn box to
  delete it (**Delete/Backspace** in the modal, or the button).
- **Mark blank** flags every kraken line on the page as non-text (3) in one step — for blank
  pages where kraken still detected spurious lines. It's a single undoable action.
- **Undo** the last saved change (flag, box add, box delete, mark-blank) with **Cmd+Z / Ctrl+Z**
  or the **Undo** button. Undo is scoped to the current page.
- Each change is saved immediately to `dev/kraken_review/reviews/page_<N>.review.json`.

### Ordering the missed lines

Kraken already returns its lines in reading order (it applies
`kraken.lib.segmentation.polygonal_reading_order` by default), so `segmentation.json`'s
`line_001..N` **is** reading order. A drawn missed-line box has no baseline yet, so the later
pipeline-integration step synthesizes one (the box's horizontal midline) and runs the whole set
— kraken lines + missed boxes — back through `polygonal_reading_order` to get a single unified
order. That merge is out of scope here; the UI just captures each box's geometry.

## Output format

`reviews/page_<N>.review.json`:

```json
{
  "page": 448,
  "reviewed_by": "human",
  "timestamp": "2026-07-23T...Z",
  "model": "blla.mlmodel",
  "num_lines": 70,
  "flags": {
    "line_012": { "category": 3, "label": "non-text" },
    "line_034": { "category": 1, "label": "over-segmentation" }
  },
  "missed_lines": [
    { "id": "missed_001", "box": [130, 220, 980, 285] }
  ]
}
```

`box` is `[x1, y1, x2, y2]` in full-resolution page pixels.

## Layout

```
dev/kraken_segment.py            geometry dump (imports kraken; run with dev venv)
dev/kraken_review/
  app.py                         FastAPI endpoints (no kraken import)
  storage.py                     filesystem layer (paths, review read/write)
  static/{index.html,app.js,styles.css}   canvas overlay + click-to-flag modal
  data/page_<N>/                 render.png + segmentation.json  (generated)
  reviews/page_<N>.review.json   saved human flags               (generated)
```

`data/` and `reviews/` are generated artifacts; see `.gitignore` in this directory.
