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
  - drag a **hollow dot** (the middle of each longer edge) to **add a vertex** there;
    **double-click** a vertex to **remove** it;
  - **Option-drag** a rectangle to add missed ink to the selected line (it's carved out of
    any neighbour it overlaps);
  - **Delete** removes it; Shift-click selects more lines, and **M** merges them.
  - The printed page number (the `-( N )-` header) is usually **already marked** when a
    page opens: "page number N (auto)" in the edit list. If it's on the wrong box, remove
    that edit with × and mark the right one with **P**.
  - **P** marks it as the printed page number: confirm the pre-filled number (PDF page − 4)
    with Enter. It leaves the lines and the reading order and is stored as a page element.
    If Paddle missed the number, drag a box over it first.

  Drag on empty page to add a new line. kraken-fill outlines follow the ink, so their dots
  are dense (simplified to within 2.5 px for editing); Option-drag is usually quicker there.
- **Split (S):** click a line, then click the cut. A plain click cuts vertically, Shift-click
  cuts horizontally.
- **Initials are usually already marked** when a page opens: "initial ? → line_NNN (auto)"
  in the edit list, found from the ink (`initials.py`). Remove a wrong one with ×.
- **Paddle's junk boxes** never reach the screen (`duplicates.py`): a box at least half
  inside another line (a line boxed twice, or a speck inside a line), and a box smaller
  than one character. If a copy is left (you'd named it in an edit), a banner says which
  line to delete.
- **Initial (I):** drag a box around the capital (or click Paddle's box over it). The
  line it will join is shown dashed while you type the letter: the line the capital
  starts, in its own column. It's carved out of any other line it overlaps; a Paddle box
  over the capital alone is deleted. Typing the letter is optional but worth it: it's kept on the
  line (`initial`) in the verified output.
- **Title (T):** box or click a section-title letter and type it. A title box sitting on the column gutter
  (a taregir letter) also interrupts the reading order there.
- **Gutter break (B):** click at the height where something interrupts the column gutter
  without a text line across it (an ornament). Reading order is column-first: each column
  reads top to bottom, and only a gutter interruption (a line across it, a title on it,
  or a break) makes the page read the band above first.
- **Delete all:** for blank pages.
- **Cmd+Z** undoes; the × next to an edit in the side panel removes just that edit.
- **← / →** change page.

A red banner flags a page whose blank marker (`data/pages/blank/`) disagrees with its
lines, and a page whose baseline changed under its review (edits are then disabled).

## Files

```
materialize.py   baseline + ops -> lines; id minting; verified record (pure)
page_number.py   finds the printed page number so a fresh review starts with it marked
duplicates.py    drops boxes inside other lines and boxes smaller than a character, before the ops
initials.py      finds initial capitals for a fresh review; the line a drawn initial joins
storage.py       paths, review read/write, status transitions, verified output
lines.py         find a line by verified id or baseline key
crops.py         line and context crops
transcribe.py    transcriptions per task, the test-set sample
migrate.py       on verify: transcriptions, picks, predictions follow the new ids
app.py           FastAPI endpoints
static/          canvas UI
```

Ops and status: `dev/lineseg_survey/paddle-filled/reviews/page_<N>.review.json`.
Verified output: `data/verified_lines/page_<N>.json`. Both are committed.

Tests: `uv run python -m pytest tests/test_line_review_materialize.py
tests/test_line_review_storage.py tests/test_verified_lines_reproduce.py`. The last one
is the gate's reproducibility check.

## Transcription (Phase 10)

`/transcribe` (or **Transcribe →** in the header): type the text of sampled verified
lines for the OCR test set (`docs/phase_10_ocr_test_set.md`). **Top up sample** adds lines
from newly verified pages; **Enter** submits and moves on; **Alt+I** illegible; **Alt+B**
bad crop (the box is wrong). The palette inserts characters a standard Armenian
keyboard makes awkward (՟ ֊ ։ ՝ ՛ ․ « » և). **Blind recheck** retypes about 1 line in 10
without showing the first pass. Pass `--contributor NAME` to record who typed. Output:
`data/transcriptions/testset/` (committed).
