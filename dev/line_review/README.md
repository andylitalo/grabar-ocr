# Phase 9 line review

Fix the `paddle-filled` baseline, then verify the result. Design and gate:
`docs/phase_9_line_segmentation_review.md`.

```bash
uv run python -m dev.line_review.app          # http://127.0.0.1:8092
```

## Workflow

| status | what you see | keys |
|---|---|---|
| unreviewed / fixing | the current lines, coloured by source (green Paddle, blue kraken fill, magenta edited), deleted lines as dashed ghosts | **Enter** = Mark fixed |
| fixed | clean view: the lines as they'll be saved, numbered in reading order, read-only | **Enter** = Mark verified (then next page), **R** = Resume fixing |
| verified | locked; ids minted, `data/verified_lines/page_<N>.json` written; hover a line for its id | **R** = Resume fixing |

Editing (fixing only):

- **Select / add (V):** click a line to select it (Shift adds more). **Delete** removes the
  selection, **M** merges it. Drag on the page to add a line.
- **Split (S):** click a line, then click the cut. A plain click cuts vertically, Shift-click
  cuts horizontally.
- **Initial (I):** drag a box around a drop cap. It joins the upper line on its right and
  is carved out of any other line it overlaps.
- **Title (T):** box or click a section-title letter and type it.
- **Delete all:** for blank pages.
- **Cmd+Z** undoes; the × next to an edit in the side panel removes just that edit.
- **← / →** change page.

A red banner flags a page whose blank marker (`data/pages/blank/`) disagrees with its
lines, and a page whose baseline changed under its review (edits are then disabled).

## Files

```
materialize.py   baseline + ops -> lines; id minting; verified record (pure)
storage.py       paths, review read/write, status transitions, verified output
app.py           FastAPI endpoints
static/          canvas UI
```

Ops and status: `dev/lineseg_survey/paddle-filled/reviews/page_<N>.review.json`.
Verified output: `data/verified_lines/page_<N>.json`. Both are committed.

Tests: `uv run python -m pytest tests/test_line_review_materialize.py
tests/test_line_review_storage.py tests/test_verified_lines_reproduce.py`. The last one
is the gate's reproducibility check.
