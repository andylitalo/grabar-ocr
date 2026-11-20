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

- **Select / add (V):** click a line to select it: it fills in and shows its vertices as
  dots. Then:
  - drag a **dot** to move that vertex, an **edge** to move that side, or the **inside** to
    move the whole box. Each drag saves on release, and repeated drags of one line count
    as one edit;
  - **Delete** removes it; Shift-click selects more lines, and **M** merges them.
  - **P** marks it as the printed page number: confirm the pre-filled number (PDF page − 4)
    with Enter. It leaves the lines and the reading order and is stored as a page element.
    If Paddle missed the number, drag a box over it first. A fresh page usually starts
    with the number already marked (`page_number.py`, shown as "(auto)" in the edit list);
    remove that edit with × if it's wrong, then mark the right box.
  - A fresh page also starts with its boxes pushed out over the letters they cut, such as
    descender tips and the tops of capitals (`unclip.py`). The edit list shows these as
    one row, "N boxes extended over cut letters (auto)", and its × removes them all.
    Reshaping one of those lines by hand adds an ordinary reshape after them, which wins;
    the auto edit stays in the row, and × on the row leaves the hand reshape.

  Drag on empty page to add a new line. kraken-fill outlines follow the ink, so their dots
  are dense (simplified to within 2.5 px for editing): drag an edge to take in clipped ink.
- **Split (S):** click a line, then click the cut. A plain click cuts vertically, Shift-click
  cuts horizontally.
- **Initial (I):** drag a box around a drop cap. It joins the upper line on its right and
  is carved out of any other line it overlaps. Typing the letter is optional but worth it:
  it's kept on the line (`initial`) in the verified output.
- **Title (T):** box or click a section-title letter and type it. A title box sitting on the column gutter
  (a taregir letter) also interrupts the reading order there.
- **Gutter break (B):** click at the height where something interrupts the column gutter
  without a text line across it (an ornament). Reading order is column-first: each column
  reads top to bottom, and only a gutter interruption (a line across it, a title on it,
  or a break) makes the page read the band above first.
- **Delete all:** for blank pages.
- **Cmd+Z** undoes; the × next to an edit in the side panel removes just that edit.
- **← / →** change page.
- **O** jumps to the next box that shows another line's letters (below).

**Paddle's junk boxes** never reach the screen (`duplicates.py`): a box at least half
inside another line (a line boxed twice, or a speck inside a line), and a box smaller
than one character. If a copy is left (you'd named it in an edit), a banner says which
line to delete.

A red banner flags a page whose blank marker (`data/pages/blank/`) disagrees with its
lines, and a page whose baseline changed under its review (edits are then disabled).

**Boxes that show another line's letters** (`overlap.py`): when a line's crop would hold
10 px or more of a neighbour's letters, its box gets a thick red dashed outline, those
pixels are painted red (the rest of that letter stays black), and each piece is ringed.
The banner lists them ("24 (75 px of 23)": line 24 holds 75 px of line 23's letters),
hovering the line repeats it, **O** steps through them, and the page list shows the count
(⚠3). It's a warning, not a block: verify a page whose flags are fine as they are.
Overlap in the blank gap between lines isn't flagged; it costs a crop nothing.

## Files

```
materialize.py       baseline + ops -> lines; id minting; verified record (pure)
unclip.py            fresh-review reshapes over letters a box cuts (page image -> ops)
unclip_verified.py   adds those reshapes to verified pages and sends them back to fixed
overlap.py           flags boxes whose crop shows another line's letters (a review warning)
duplicates.py        drops boxes inside other lines and boxes smaller than a character, before the ops
page_number.py       finds the printed page number so a fresh review starts with it marked
storage.py           paths, review read/write, status transitions, verified output
baseline_manifest.py checks paddle-filled against baseline_sha256.json (--accept to update)
rewrite_verified.py  rewrites verified files after a format change (--reopen for content changes)
lines.py             find a line by verified id or baseline key
crops.py             line and context crops
transcribe.py        transcriptions per task, the test-set sample
migrate.py           after the layout review (`repair`): transcriptions, picks, predictions move to line ids
app.py               FastAPI endpoints
static/              canvas UI
```

Ops and status: `data/lineseg_survey/paddle-filled/reviews/page_<N>.review.json`.
Verified output: `data/verified_lines/page_<N>.json`. Both are committed.

Tests: `uv run python -m pytest tests/test_line_review_*.py tests/test_verified_lines_reproduce.py
tests/test_baseline_manifest.py`. The last two are the gate's reproducibility and baseline
checks.

## Transcription (Phase 10)

`/transcribe` (or **Transcribe →** in the header; `?set=ceiling` for the ceiling sample,
`?line=p468.021` to open one sampled line): type the text of sampled verified
lines for the OCR test set (`docs/phase_10_ocr_test_set.md`). **Top up sample** adds lines
from newly verified pages; **Enter** submits and moves on; **Alt+I** illegible; **Alt+B**
bad crop (the box is wrong). The palette inserts characters a standard Armenian
keyboard makes awkward (՟ ֊ ։ ՝ ՛ ․ « » և). **Blind recheck** retypes about 1 line in 10
without showing the first pass. Pass `--contributor NAME` to record who typed. Output:
`data/transcriptions/testset/` (committed).
