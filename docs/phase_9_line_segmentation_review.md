# Phase 9 — human review of line segmentation

**Status:** building (step 1 done 2026-10-02) · **Created:** 2026-09-30 · **Owner:** —
**Depends on:** `docs/phase_8_line_segmentation_survey.md`, which supplies the chosen
baseline segmenter's output for pp.453–643 in the common `segmentation.json` format.
**Baseline (chosen 2026-09-30):** `paddle-filled`: hyocr-paddle lines plus the kraken lines
Surya agrees on and Paddle lacks (`dev/lineseg_survey/paddle-filled/`). Filled lines carry
`"source": "kraken-fill"`.
**Feeds:** line/page/section enumeration, then OCR (`docs/backlog/README.md`).

## Goal

Turn the baseline segmenter's output into **verified line segments** for every content page,
each with a **stable line id**. This is the foundation for citation and for all later OCR.
Verified means a human has looked at the page and every line polygon is correct.

## Starting point

This phase extends `dev/kraken_review/` (see `docs/kraken_line_segmentation.md`). The UI
already has these tools:

- **flag:** over-segmentation, under-segmentation, non-text
- **missed line:** drag a box
- **initial:** attach a drop-cap to its line
- **merge** and **split**
- **section title:** box a titular letter

Its edits are stored as declarative ops on top of the tool's immutable output. That design
carries forward. Step-2 ops have never been used on real pages, so Phase 9 is their first
real test.

## Review workflow: fix, then verify (maintainer, 2026-09-30)

Each page goes through two passes, so the final boxes are checked as they will actually be
saved, not as a pile of annotations:

```
unreviewed ──► fixing ──[Mark fixed]──► fixed ──[Mark verified]──► verified (locked)
                  ▲                       │                              │
                  └─────[Resume fixing]───┴─────────[Resume fixing]──────┘
```

1. **Fixing.** The baseline boxes are shown with the editing tools. Every correction is
   recorded as an op on top of the immutable baseline (as today).
2. **Mark fixed.** The materializer applies the ops. The screen then switches to a **clean
   view**: the resulting boxes only, with the fix-up annotations (flags, merge groups,
   split cuts, initial connectors) hidden, plus the reading-order numbers.
3. **Verify.** The reviewer checks the materialized boxes. **Mark verified** finalizes and
   locks the page; this is the geometry that later stages read.
4. **Something wrong in the clean view → Resume fixing.** That goes back to the ops on
   the baseline, rather than editing the materialized boxes directly. Raw baseline + ops
   stays the single source of truth, which is what the reproducibility gate below needs.

Because the clean view shows only what the ops produced, every Phase 9 problem must be
*fixable*, not just flaggable. Survey-style flags (1, 2, 4) have no effect on the
materialized geometry, so in Phase 9 each becomes an edit op. Category 3 (non-text) is the
exception: the materializer drops those lines.

## Design (agreed 2026-10-02)

### Edits: a short ordered op list on the immutable baseline

Every reviewer action is saved as one of a few ops, applied in order to
`data/lineseg_survey/paddle-filled/pages/page_<N>/segmentation.json`. The survey's flags 1, 2, 4 and 5 go away;
each one is now a geometry edit.

| op | replaces | effect |
|---|---|---|
| `delete(line)` | flag 3 (non-text) | line removed |
| `reshape(line, polygon)` | flag 4 (clips ink); also vertex drag, grow, redraw | the line gets a new polygon |
| `add(polygon)` | missed-line box | a new line (a drawn box is a 4-point polygon) |
| `split(line, cut)` | split (vertical only today) | `cut` is any polyline across the line: vertical for gutter-fused headers, horizontal for lines stacked one above the other |
| `merge(lines)` | merge | lines joined into one |
| `initial(box, line)` | initial | box unioned into `line` and subtracted from every other line it overlaps |
| `grow(box, line)` | (new) | same geometry as `initial`, without a letter: takes missed ink into a line |
| `page_number(line \| box, value)` | (new) | the printed page number: taken out of the lines and the reading order, stored as a page element `{value, box}` |
| `break(y)` | (new) | the column gutter is interrupted at `y` (see reading order below) |
| `order(lines…)` | flag 5 (reading order) | explicit reading order for the page |

Section titles stay as page annotations and don't change geometry. Lines created by an op
get deterministic keys so later ops can refer to them: `line_012/1`, `line_012/2` for the
halves of a split, `add_001`… for added lines. The UI can offer richer tools than this
table, but every action saves as one of these ops.

The **materializer** is a pure function, baseline + ops → final lines, written test-first.
**Default reading order is column-first** (maintainer, 2026-10-03), not the baseline's:
Paddle's X-Y cut splits the page horizontally wherever the two columns' gaps line up
(p.460). Rule: find the gutter (the middle of the widest x-run no line crosses); each
column reads top to bottom, and the page splits into bands only where the gutter is
interrupted, by a line that crosses it, a section-title box on it (a taregir letter), or a
`break` op. Boxes on one row (a drop cap and its line, a title in pieces, "1." beside a
title) read left to right. An explicit `order` op overrides the rule. Over the book it
changes the order on 60 pages outside the header band; checked by eye on pp.460, 462
(a fill that had been put last), 471, 575 and 610. All six reviewed pages keep their order.

### Stable line ids

- **Format `p<PDF page>.<NNN>`**, e.g. `p617.023`. The PDF page is used, not the printed
  page (printed = PDF − 4; title and illustration pages have no printed number). Printed
  numbers go in a separate page → printed map.
- **Minted at the page's first Mark verified.** `NNN` is the line's reading-order position at
  that moment, so ids and order agree at first. The id assignments are saved in the review
  file, so re-running the materializer reproduces the ids too.
- **Ids are permanent, and reading order is a separate field.** Re-editing a line keeps its id.
  A line added later gets the next unused number and is placed by `order`; nothing is
  renumbered. A split or merge retires the old id and records `superseded_by`. Ids are never
  reused.
- Content hashes belong on entries, not lines (roadmap §5): line ids only need to stay
  stable for entry → line links.

### Baselines

Paddle lines and added lines keep the synthetic baseline (a straight line ¾ of the way down
the box), tagged `baseline_source: "synthetic"`. kraken-fill lines keep kraken's baseline
(`"kraken"`). The OCR engines to be compared read line crops, not baselines. Real
baselines can be computed from the ink later if a kraken-style consumer needs them.

### Missed-line guard (blocks verification)

On Mark fixed, the server finds ink blobs that no final line covers, ignoring speckle and
long horizontal rules (the same measures as the fill filter, `ensemble.nontext_reason`).
The clean view shows the blobs, with `filtered_fills` as faint ghost boxes. **Mark verified
is refused until every blob is resolved**: either an `add` covers it, or it is dismissed as
non-text with one key. Dismissals are saved as ops, so a blob isn't raised again.

### Pages, storage, output

- Page status in the review file: `unreviewed → fixing → fixed → verified`, with a coverage
  view over 453–643. A blank page is verified with zero lines and cross-checked against the
  blank markers in `data/pages/blank/`.
- Ops are the source of truth: `data/lineseg_survey/paddle-filled/reviews/page_<N>.review.json`
  (committed).
- The materialized output is committed too: **`data/verified_lines/page_<N>.json`**
  (allow-listed in `.gitignore` like `data/columns/boxes/`), one record per line:
  `id`, `order`, `boundary`, `baseline`, `baseline_source`, `bbox`, `source`
  (`hyocr-paddle` / `kraken-fill` / `human`), `derived_from`, `initial` (the drop-cap
  letter, if typed). Page elements sit beside the lines: `page_number` `{value, box}` and
  `section_titles` `[{letter, box}]`. A test checks that
  re-materializing reproduces every committed file byte for byte.

### Build order

1. **The core:** the op schema, the materializer (test-first), the status states, the clean
   view and id minting. Pages that only need deletes and adds can already be verified.
2. **Geometry editing:** vertex drag, redraw, split along any polyline.
3. **The missed-line guard.**
4. **Reading-order display and fixes.** Paddle made 0 order errors on the sample, so this
   comes last.
5. **The coverage view.**

Also: a one-off script carries the 11 reviewed sample pages' Paddle fixes over to
`paddle-filled` by matching geometry, since those reviews point at `hyocr-paddle` line ids.

## Build log

- **2026-10-02, step 1 done.** New package `dev/line_review/` (see its README), run with
  `uv run python -m dev.line_review.app`. It is a new package rather than an extension of
  `dev/kraken_review`, whose flag-format reviews `score.py` still reads for the Phase 8
  tables. It reuses that app's canvas approach and the initial-target rule. Built:
  - the materializer, implementing every op in the table above (geometry via `shapely`, now a
    repo dependency), plus id minting and the verified record, all test-first
    (`tests/test_line_review_materialize.py`, 24 tests);
  - storage with the status rules and a baseline-hash guard (`tests/test_line_review_storage.py`);
  - the reproducibility check for committed output (`tests/test_verified_lines_reproduce.py`);
  - the UI: fixing view (lines coloured by source, deleted lines as ghosts, edit list with
    per-edit removal, undo), clean view with reading-order numbers, Enter to advance, and
    a banner when the blank markers disagree with the lines.

  Smoke-tested in a browser on temp copies of pp.453, 457, 495: delete, add, split, undo,
  fix → verify (ids and output file written), auto-advance. Already usable for pages that
  need only deletes, adds, splits, merges and initials. Still to come: vertex reshape
  (step 2), the missed-line guard (step 3), the reading-order editor (step 4), the
  coverage view (step 5), and carrying the sample reviews over.
- **2026-10-02, step 2 started (maintainer's spec).** Click a line to select it: it fills
  and shows its vertices as dots. Drag a dot, an edge (moves both endpoints, so a Paddle
  quad grows one side at a time) or the inside (moves the box); each drag saves a
  `reshape` on release, and back-to-back reshapes of one line collapse into one op.
  kraken outlines have ~100 points, many duplicated; handles use a Ramer-Douglas-Peucker
  simplification within 2.5 px (median 37 points; coarser tolerances change the area by up
  to 18%), so **Option-drag** adds a rectangle of missed ink to the selected line (new
  `grow` op). Remaining for step 2: adding and removing vertices.

## Gate

- Every content page in 453–643 is marked verified. Blank pages are confirmed blank.
- Every verified line has a stable id, a polygon, a baseline (synthetic allowed, tagged) and a
  reading-order position.
- No verified page has unresolved uncovered ink.
- Re-running the materializer from raw output + ops reproduces the verified geometry
  exactly.

## Out of scope

OCR, transcription ground truth, entries, and the citation UI (see `docs/backlog/README.md`).
- **2026-10-02: page numbers and drop-cap letters (maintainer).** Printed page numbers are
  page elements, not text: kept (they're the reader's citation page and they verify the
  PDF → printed map, printed = PDF − 4) but outside the lines and reading order. New op
  `page_number`, key **P** on a selected box, pre-filled with PDF − 4; a mismatch is
  flagged. Typed drop-cap letters and section-title letters now reach the verified
  output too. Fixed: an initial box that doesn't touch its line was joined by a convex
  hull that could cut across the next line; the gap is now bridged inside the shared rows.
  **Open:** running headers (the text beside the page number): lines or page elements?
- **2026-10-03: column-first reading order** (maintainer's rule: columns first while the
  gutter runs unbroken, a horizontal split only where it's interrupted). See "Default
  reading order" above. New `break` op (tool **B**) for interruptions with no line on
  them; section titles on the gutter count too. Image-based detection of breaks in the
  printed gutter rule was tried and dropped: too noisy (107 pages flagged).
- **2026-10-15: PR #3 review fixes.** Saves and page loads now go one at a time in the
  UI, and each review carries a `revision` the server checks, so a quick page change or a
  second tab can't put one page's ops on another or drop an edit. A double Enter
  registers once. Add keys are never reissued (`add_keys` in the review), so a new box
  can't inherit a retired line's id. Resume fixing marks the verified file `resumed_at`;
  re-verifying rewrites it whole. `baseline_sha256.json` records all 191 paddle-filled
  pages (`python -m dev.line_review.baseline_manifest`). Merges across a gap subtract the
  other lines in it, and are refused if a line cuts the gap or sits inside it. A kraken
  baseline is cut to a trimmed line's width. Section titles must be 1-4 Armenian letters.
  `rewrite_verified` only rewrites format changes; a change to verified ids, order or
  geometry is refused unless `--reopen` sends the page back for review. **Option-drag
  (`grow`) is removed** (never needed in 41 pages; reshape takes in clipped ink, initial
  takes drop caps); old `grow` ops still materialize. Initial boxes that share no rows
  with their line, or would cut another line in two, are refused (neither happened in
  the 41 reviews).
- **2026-10-15: Paddle's junk boxes, from `feat/layout-review`.** `duplicates.py` drops,
  before the ops, the smaller of two boxes when it lies at least half inside the other (a
  line boxed twice, or a speck inside a line) and boxes smaller than one character; an op
  that names a box keeps it, and a banner names any copy left. The 10 verified pages here
  are unchanged. Of the 40 verified on `feat/layout-review`, 39 reproduce under this code;
  p.490 differed only in `line_083`'s kraken baseline, now cut to its reshaped box (x 1168
  → 1195): `rewrite_verified` refused it, `--reopen` sent it back, and it was re-verified
  (ids unchanged).
- **2026-10-15: reviews 463-493 brought over from `feat/layout-review`** (moved from
  `dev/lineseg_survey/` to `data/lineseg_survey/`): 40 pages verified (453-492), p.493
  still fixing. All 40 verified files reproduce. Not ported: the layout branch's automatic id retirement in `rewrite_verified`
  (verified content now changes only through a re-verify) and the fresh-review auto ops.
- **2026-10-31: fixes from the second PR #3 review** (code and data now in separate PRs):
  - **Saves are serialized.** Each page has a lock from the revision check to the write.
    Files are written to a temp file and renamed into place. In the UI, the page after a
    verify loads inside the queued job.
  - **A split piece's id follows its cut.** Each line carries the `cuts` that made it, and
    the review records them per id (`id_cuts`). A `KEY/1` that comes back from a different
    cut gets a new id, and the old one is retired. Ids minted before this keep theirs.
  - **Initials in a notch bridge without a hull.** When the boxes overlap in x but the
    outlines don't touch, the bridge is the hull of the two outlines inside the shared
    rows. If they still don't join, the op is refused (no convex-hull fallback).
  - **Merged kraken baselines.** A merge keeps a kraken baseline only for members side by
    side on one row, cut to the merged box. Otherwise the baseline is synthetic.
  - **Reshape keeps detail.** A drag moves the handles and bends the full outline between
    them; the simplified handle ring is no longer saved as the boundary.
  - **Validation.** An initial is one Armenian letter, and a page number is 1-4 digits.
    The panel escapes what it shows.
  - **`rewrite_verified`.** It also treats `initial`, `source` and `derived_from` as
    verified content, and a page whose ops no longer apply is refused (or reopened), not
    a crash.
  - **Less repeated work.** A save or verify materializes once, and reads and hashes the
    baseline once.
