# Phase 9 — human review of line segmentation

**Status:** review done, gate passed 2026-11-23; "After the gate" steps 2-4 open · **Created:** 2026-09-30 · **Owner:** —
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
- **2026-10-11, transcriptions follow verification.** Phase 11's ceiling sample was typed
  on unverified pages under baseline keys (`p520~line_013`), which stop resolving once a
  page is verified. `set_status(…, "verified")` now calls `dev/line_review/migrate.py`:
  every transcription records the shape it was typed against (`geometry`, a fingerprint
  of the boundary; the 165 existing records were backfilled with
  `python -m dev.line_review.migrate backfill`). On verify, a line with the same shape
  takes its transcription, sample pick, OCR predictions and crop to its new id. A reshaped,
  split, merged or deleted line's transcription moves to `data/transcriptions/<task>/stale/`
  and the line shows untyped. A page-level corrector's (`corr-*`) whole page is dropped if
  any of its lines changed, to be re-corrected. The same check covers re-verifying a page
  whose test-set lines were reshaped. `lines.find` also resolves a verified id while its
  page is back under review. Tests: `tests/test_line_review_migrate.py`.
- **2026-11-13, the migration moves to the end of the review (PR #2 review, maintainer).**
  No transcription or OCR runs until the layout review is done, so verify no longer calls
  `migrate`: it mints ids and writes the verified file, as before 2026-10-11. The data is
  moved once, by `python -m dev.line_review.migrate repair`, after the gate ("After the
  gate"). Running it inside each verify could leave data on ids that were never saved
  when it failed partway, and could race an OCR run rewriting the same files. `repair`
  now maps every key the page's data uses: a line the review added and then removed sends
  its transcription to `stale/` and its pick to `dropped` instead of leaving them behind;
  an added line's predictions and crop are dropped (its shape when they were made is
  unknown); a retry doesn't set a stale record aside twice; and a crop already exported
  under the new id replaces the old one. Predictions are written atomically.
  **Corrector output is kept line by line (maintainer: the scores must not move).** A
  `corr-*` page is no longer dropped when one of its lines changes: a line's own two
  readings are the corrector's input, so its correction of an unchanged line stays valid
  and moves to the new id like any engine's prediction. No prediction is deleted: a changed
  line's goes to the file's `stale` section (`{old key: [{text, reason, replaced_by, at}]}`),
  which the scorer doesn't read and rewrites keep; a rewrite that drops a line, or replaces it with a different reading, sets the old reading aside there too (`common.set_aside`, 2026-11-13; entries in both cases carry `predicted_before`, and `settings` only when the file's `uniform_settings` says they're known). `repair` first locks every predictions file, so it stops if a run is writing one. `correct.py` sends a page again only if
  some of its lines have no correction, and writes only those. A trial `repair` on pages
  493–494 (PR #9's data) left `reports/phase11_ceiling.md` unchanged. Tests:
  `tests/test_line_review_migrate.py`, `tests/test_ocr_eval_ceiling.py`.

## Gate

- Every content page in 453–643 is marked verified. Blank pages are confirmed blank.
- Every verified line has a stable id, a polygon, a baseline (synthetic allowed, tagged) and a
  reading-order position.
- No verified page has unresolved uncovered ink.
- Re-running the materializer from raw output + ops reproduces the verified geometry
  exactly.

## After the gate

**During the review: repair per batch (maintainer, 2026-11-17).** Verify doesn't move the
Phase 10/11 data. The ceiling sample was typed on baseline keys, and the transcribe page
can't open a baseline-keyed pick on a verified page. So each batch's data PR also runs
`uv run python -m dev.line_review.migrate repair` (it only moves verified pages, and a
second run prints nothing) in its own commit, as #13 and #15 did. The PR description says
what moved, what went to `stale`, and which typed lines to retype.

Lines set aside to retype can then be retyped right away (`/transcribe?set=ceiling&line=<id>`).
Don't type in the transcribe page while `repair` runs: transcription files take no lock
across processes yet. Engine and corrector runs still wait for step 3 below, so the paid
run happens once.

After the whole review, move the rest before any new OCR:

1. `uv run python -m dev.line_review.migrate repair`; run it again until it prints nothing
   (it is idempotent, so a failure partway is fixed by re-running). After per-batch
   repairs, this only moves the last batch, if anything.
2. Read the diff of `data/transcriptions/` and `data/ocr_predictions/`: picks moved to ids,
   records of reshaped lines in `stale/`, predictions of changed lines moved to each file's
   `stale` section. Re-score: `reports/phase11_ceiling.md` must not change apart from
   line names and the typed lines whose shape changed. Those lines are listed in each
   batch PR; they drop out of the score until step 3 re-runs the engines on them, even
   after they are retyped. Commit it on
   its own (data commit).
3. Retype the stale lines, run the engines on the lines without predictions, then the
   corrector (it fills only the lines it hasn't corrected), and re-score.
4. **Recompute the strata** (`docs/phase_11_ocr_comparison.md`, "Where this stands",
   "Open"). Two things in `data/transcriptions/ceiling/sample.json` come from the two
   engines' output at the time the sample was drawn, mostly on baseline lines: the
   `population` (how many book lines the engines agree and disagree on) and each pick's
   `stratum`. After step 3, the engines cover every verified line, so recompute both
   from their current output, comparing as `ceiling.sample` does.
   - Picks keep their ids. Only the `stratum` values and the `population` change.
   - Don't re-run `ceiling sample`: it would draw a new sample.
   - So far one pick has flipped: `p467.061`, drawn as an agreement.

   Recomputing needs a small code change. The population sets each stratum's weight,
   so every rate moves. Re-score, record in the Phase 11 doc how the numbers moved,
   and commit the report: it is the reference for the region conversion
   (`docs/backlog/region_keyed_data.md`, "Migration", step 1).

Code and the data it writes go in separate PRs when the data is large (AGENTS.md, "Data
storage").

Then the book-wide run starts by moving the data to region keys
(`docs/backlog/region_keyed_data.md`).

## Out of scope

OCR, transcription ground truth, entries, and the citation UI (see `docs/backlog/README.md`).
- **2026-10-02: page numbers and drop-cap letters (maintainer).** Printed page numbers are
  page elements, not text: kept (they're the reader's citation page and they verify the
  PDF → printed map, printed = PDF − 4) but outside the lines and reading order. New op
  `page_number`, key **P** on a selected box, pre-filled with PDF − 4; a mismatch is
  flagged. Typed drop-cap letters and section-title letters now reach the verified
  output too. Fixed: an initial box that doesn't touch its line was joined by a convex
  hull that could cut across the next line; the gap is now bridged inside the shared rows.
  **Decided 2026-10-11 (maintainer):** the running header `-( <page-number> )-` is part
  of the page number, not a text line, so it is marked with the `page_number` op. This
  is what lets the page number be marked automatically (2026-11-13 below).
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
  - **Verified files are diff-friendly.** `mz.dumps` writes one top-level field per line
    and one compact record per line of text, with polygons inline (AGENTS.md "Data
    storage"). The 40 verified files were rewritten format-only with `rewrite_verified`:
    162,389 lines down to 3,211, with the same JSON content.
- **2026-11-13: the page number is marked automatically again.** `page_number.py` (from
  `feat/layout-review`, 8e0acf7) had been left out of PR #3, so p.494, the first page
  reviewed on `main`, started with no page-number edit and was marked by hand. A fresh
  review now starts with a `page_number` op (`"auto": true`, value PDF − 4) when the top
  line is small, centred and high. It agrees with the hand marks on all 42 reviewed pages
  (453-494; none on 453-457 and 481-483), and book-wide it leaves exactly the 27 known
  unnumbered pages unmarked. Over pp.453–643 it marks the 164 numbered pages: 152 by
  Paddle's box and 12 by a kraken fill over the digits where Paddle missed the number.
  The value always comes from the PDF page, never from Paddle's reading of the digits,
  which is often wrong (p.459 reads "458"). Only pages without a review file are seeded.
  Automatic initials (`initials.py`) were not ported.
- **2026-11-17: boxes start pushed out over the letters they cut (`unclip.py`).** Paddle's
  boxes often run along the tips of descenders (ր ը զ ց ղ դ ք յ) or just under a capital's
  top, and a line crop whitens everything outside the box, so a 1-3 px cut can turn ր into
  ը or ղ into դ. On pp.453-516 the baseline cut 2,257 letters (by 3 px or more) in 1,082
  of 4,708 lines; the verified output still cuts about 2,000, so review by hand had fixed
  about one in ten. A fresh review now starts with a `reshape` op (`"auto": true`) for
  each line that cuts one of its own letters: the box takes in that letter's bounding box
  + 2 px, only over its columns, never inside another line's box and never within 2 px of
  another line's letter (a neighbour's capital often sticks out of its own box right
  there). The rule and its thresholds are in the module docstring.
  - **Measured.** Book-wide, as fresh reviews: letters cut by 3 px or more 5,511 → 120;
    184 of 191 pages get ops (median 51 lines a page); no letter of another line newly
    taken in; reading order unchanged on every page; 0.27 s a page. Padding every box
    by 8 px instead left 231 of the 2,257 cut but took in 18.9k px of other lines' ink,
    so it was rejected. The margin is 2 px because the page's grey anti-aliased edge is
    exactly 1 px wide; 3-6 px freed no more letters and, before the guard, took in more
    of the neighbours' letters.
  - **Checked by the maintainer's flags.** All 8 lines flagged on fresh pp.518-519 (the
    tops of Ո Շ Ե Չ Ի; descenders of Ե, զրկկղիիգ and րպկրկ) end with none of their
    letters' ink outside the box (`test_flagged_lines_lose_no_ink`), and a sample of
    unflagged extended lines took nothing from the lines around them.
  - **Drop caps stay with review.** A blob no other box touches joins a line only up to
    1.5 line heights. At 2 the rule took p.460's two-line drop cap into one line, raised
    that box above the line before it and changed the reading order; `initial` attaches
    drop caps. A decorated capital's swash that no box touches isn't attached either
    (stray-blob rules picked the wrong line or junk); review catches it, and a tool for it
    waits until it proves frequent.
  - **Specks are left out (maintainer, 2026-11-18).** On the sample sheet, a few boxes
    reached into the gap between lines for a speck or a stray print mark (pp.464, 479,
    497). Of the 32,237 blobs the rule extended over book-wide, 144 were small (under 150
    px) and sat entirely above or below their line's text band; looked at one by one,
    most are real: apostrophes ՚, accents and end-of-word marks above the last letter,
    and broken letter tips, all 0-5 px from a letter, the same as the specks. Two
    narrower rules leave out 34 blobs on 30 pages, all specks or print marks in the gap
    (one, a tilde under p.467's capital Ո, may be a ՟; leaving it out only keeps that line
    as it was verified): a small blob **below the text** at least 3 px from the line's
    letters (Grabar has no marks under the line, and a descender is part of its letter's
    blob), and a small blob **at least as close to another line's letters** as to its
    own. A speck above the text (p.497) can't be told from an accent this way and is still
    taken in. Book-wide this leaves 147 letters cut by 3 px or more instead of 120 (the
    difference is the specks); no other line's letters, no reading-order change.
  - **Tips are carved out of the next box (maintainer, 2026-11-18).** After the speck rules,
    113 of the 147 letters left cut had a tip (mostly descenders, յ ր կ ք) inside the next
    line's box, where the rule doesn't extend. Now the tip, plus 2 px, is cut out of that
    box, as `initial` does for a drop cap, and the letter's own box takes it in. Not
    within 2 px of that box's own letters, and never splitting it. Book-wide: letters cut
    by 3 px or more 147 → 48 (28 of them specks left out; 14 tips next to the other
    line's letter; 2 that would split a box; 4 lose a pixel or two to rounding). Checked
    by geometry (pixel centres in the polygons), not raster fill: no line loses any of its
    own letters' ink, other lines' letters gain 7 px in all (at most 2 px a line, the
    snapping sliver), reading order unchanged. Two fixes on the way: boxes are snapped to
    the 0.1 px grid of the review file while they're built (notches had folded into
    self-intersections when rounded, on 42 pages), and the 0.5 px simplify is gone (it
    cut corners into carved notches, so 57 extensions were refused for the overlap).
    0.3-0.9 s a fresh page. In review (PR #21) two guards were added: a tip is carved only
    when its letter's own box then takes it in (p.628's line_044 had lost 639 px² for
    line_043, whose extension was refused over a 3.5 px² sliver, so the tips sat in
    neither box; 3 boxes on pp.550, 628, 636 keep their shape now), and a hole the
    extension closes is filled only if it holds no guarded ink or other box (no page
    changes). The 64 verified pages' ops are identical with both guards, so the
    re-verified pp.453-516 stand.
  - **Review UI and files.** The edit list shows the auto reshapes as one row ("N boxes
    extended over cut letters (auto)"); its × removes them all. Reshaping such a line by
    hand adds an ordinary reshape after its auto op, which wins; the auto op stays in the
    row, and × leaves the hand reshape. Review files now write one op per line (polygons
    inline, the rest unchanged `indent=1`), so 50-80 notched polygons stay about 70 lines
    of file; older review files change format the next time they're saved.
  - **Ceiling transcriptions.** 77 of the 107 ceiling lines typed on pages not yet
    reviewed (519-640) are reshaped, so `migrate repair` sets their text aside as a
    prefill to re-check and their old OCR readings (of the cut crops) as stale
    (maintainer, 2026-11-17). Only pages without a review file are seeded, so the
    verified pages (453-516) and p.517 keep their cut letters. For them,
    `python -m dev.line_review.unclip_verified 453-516` adds the same ops to each verified
    review and sends the page back to `fixed`, so it is re-verified by eye (ids are kept);
    on pp.453-516 it extends 3,390 of 4,708 lines. After re-verifying, run
    `migrate repair --previous REV`, REV being a commit with the earlier verified output:
    plain `repair` takes a live verified id as unchanged, so the stored OCR readings of
    its old, clipped crop would stay; with the earlier shapes they are set aside. That is a data step of its own, and it
    sets aside the stored OCR predictions of the changed lines (Phase 11 is re-scored on
    the new crops; maintainer, 2026-11-17).
- **2026-11-20: boxes that show another line's letters are flagged (`overlap.py`).** To
  point review at them, as the zoomed sheet did for the unclip re-verify. A line is
  flagged when its crop (the same polygon mask `crops.line_crop` whitens with) holds 10 px
  or more of letters another line owns, by unclip's ownership rule, or for a letter that
  rule leaves to no one, the box holding the most of it (an exact tie to one of the tied
  lines by a hash of the letter's position; specks under 150 px stay no one's). Without
  that, a box dragged over a third of a neighbour's letter cleared its own flag. Overlap
  in the blank gap between lines isn't flagged. The UI outlines the box, paints those pixels and rings
  each piece, lists them in the banner, steps through them with O, and counts them in the
  page list. A warning only: some are fine as they are. 10 px is the threshold the
  re-verify was checked at (maintainer: no noisier), and on pp.453-516 it flags exactly
  the 10 lines left then, all Paddle's own boxes. Fresh pp.517-643: 173 flags on 81
  pages. About 0.05 s a page; the page list's counts fill in the background at startup.
- **2026-11-23: the layout review is done; gate passed.** pp.517-643 verified, so every
  page in 453-643 is: 191 pages, 14,709 lines, 7 blank pages (each with a blank marker).
  Checked in code: every line has an id, polygon, baseline and order position; no page's
  baseline changed under its review; `test_verified_lines_reproduce` passes. Uncovered ink
  has no automatic check: it rests on the review. p.641, a table of taregir letters by
  year, reads row by row through an explicit `order` op: the column-first rule found a
  gutter in a gap the rows share and read the table's left block before its right one.
  `migrate repair` on pp.517-643 set aside 79 ceiling records whose line changed shape
  (75 reshaped only by the auto-unclip): 78 typed lines to retype and one "bad crop" mark
  (`p549.047`) to judge again on the new crop. It dropped 5 untyped picks on removed lines
  (492 left). Until step 3, the ceiling scores 42 typed lines instead of 120: of the 83
  still typed, the 41 retyped in #23 wait for the engines. The committed report (160
  lines) is older than both, so its numbers aren't comparable to 95.0%.
  Then the last 10 boxes the foreign-ink check flagged (all on pp.453-516) were reshaped
  and verified again, with 2 neighbours; no flags are left in 453-643, and no typed line
  or pick was affected.
