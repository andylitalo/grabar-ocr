# Phase 9 — human review of line segmentation

**Status:** planned (starts after Phase 8's gate) · **Created:** 2026-09-30 · **Owner:** —
**Depends on:** `docs/phase_8_line_segmentation_survey.md`, which supplies the chosen
baseline segmenter's output for pp.453–643 in the common `segmentation.json` format.
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

## What needs building (to be refined once the baseline is chosen)

1. **Edit, not just flag.** Categories 1 and 2 are flag-only today. Reviewers need to fix
   geometry directly: move, add or delete polygon vertices, and redraw a line.
2. **Reading order.** Show the order and let the reviewer fix it. Missed-line boxes need a
   synthesized baseline so they slot into the order.
3. **Apply the ops.** A materializer turns raw output + ops into one verified geometry file
   per page.
4. **Page status + coverage.** Unreviewed / in progress / verified per page, with a coverage
   view over 453–643.
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
