# Phase 9 — human review of line segmentation

**Status:** planned (starts after Phase 8's gate) · **Created:** 2026-09-30 · **Owner:** —
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

## What needs building (to be refined once the baseline is chosen)

1. **Edit, not just flag.** Categories 1 and 2 are flag-only today. Reviewers need to fix
   geometry directly: move, add or delete polygon vertices, and redraw a line. The
   Split tool only cuts **vertically** (built for header lines fused across the column
   gutter). Lines fused **one above the other** need a horizontal cut too, ideally
   following the inter-line gap rather than a straight line. Clipped ink (flag 4) needs a
   way to grow a polygon.
2. **Reading order.** Show the order and let the reviewer fix it. Missed-line boxes need a
   synthesized baseline so they slot into the order.
3. **Apply the ops.** A materializer turns raw output + ops into one verified geometry file
   per page.
4. **Page status + coverage.** The four states above per page, persisted in the review
   JSON (the survey's `status` field extends to `fixing` / `fixed` / `verified`), with a
   coverage view over 453–643.
6. **Missed-line aid.** Highlight ink no box covers, so the rare remaining missed line
   (Phase 8 §5.4) can't slip through the clean view.
5. **Stable line ids.** Mint ids from the *verified* geometry, not the tool's raw numbering,
   because re-running the tool renumbers raw lines. How ids are formed, and how they survive
   later edits, is this phase's key design decision. Record it here before minting.

## Gate

- Every content page in 453–643 is marked verified. Blank pages are confirmed blank.
- Every verified line has a stable id, a polygon, a baseline and a reading-order position.
- Re-running the materializer from raw output + ops reproduces the verified geometry
  exactly.

## Out of scope

OCR, transcription ground truth, entries, and the citation UI (see `docs/backlog/README.md`).
