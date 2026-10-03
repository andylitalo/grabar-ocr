# Phase 9 — human review of line segmentation

**Status:** design agreed 2026-10-02; build not started · **Created:** 2026-09-30 · **Owner:** —
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
`paddle-filled/data/page_<N>/segmentation.json`. The survey's flags 1, 2, 4 and 5 go away;
each one is now a geometry edit.

| op | replaces | effect |
|---|---|---|
| `delete(line)` | flag 3 (non-text) | line removed |
| `reshape(line, polygon)` | flag 4 (clips ink); also vertex drag, grow, redraw | the line gets a new polygon |
| `add(polygon)` | missed-line box | a new line (a drawn box is a 4-point polygon) |
| `split(line, cut)` | split (vertical only today) | `cut` is any polyline across the line: vertical for gutter-fused headers, horizontal for lines stacked one above the other |
| `merge(lines)` | merge | lines joined into one |
| `initial(box, line)` | initial | box unioned into `line` and subtracted from every other line it overlaps |
| `order(lines…)` | flag 5 (reading order) | explicit reading order for the page |

Section titles stay as page annotations and don't change geometry. Lines created by an op
get deterministic keys so later ops can refer to them: `line_012/1`, `line_012/2` for the
halves of a split, `add_001`… for added lines. The UI can offer richer tools than this
table, but every action saves as one of these ops.

The **materializer** is a pure function, baseline + ops → final lines, written test-first.
Default reading order is the baseline's, with added lines slotted in by
`ensemble.insert_in_order`; an `order` op overrides it.

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
- Ops are the source of truth: `dev/lineseg_survey/paddle-filled/reviews/page_<N>.review.json`
  (committed).
- The materialized output is committed too: **`data/verified_lines/page_<N>.json`**
  (allow-listed in `.gitignore` like `data/columns/boxes/`), one record per line:
  `id`, `order`, `boundary`, `baseline`, `baseline_source`, `bbox`, `source`
  (`hyocr-paddle` / `kraken-fill` / `human`), `derived_from`. A test checks that
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

## Gate

- Every content page in 453–643 is marked verified. Blank pages are confirmed blank.
- Every verified line has a stable id, a polygon, a baseline (synthetic allowed, tagged) and a
  reading-order position.
- No verified page has unresolved uncovered ink.
- Re-running the materializer from raw output + ops reproduces the verified geometry
  exactly.

## Out of scope

OCR, transcription ground truth, entries, and the citation UI (see `docs/backlog/README.md`).
