# Phase 6 — Column Detection v2: regions, frame/divider/margin cleanup

*Status: PLANNING (no code until the gate below is agreed). Successor to the headless
two-column slicer (`data_prep/{deskew,column_detector,auto_slice,validate_columns}.py`).*

## Why this phase exists

Phase A (non-character detector validation) FAILED its gate — precision 92.7% (3
false positives), recall 70.4% over 17 auto pages — and the post-mortem
(`slice_categorization_findings_and_next_steps.md`) showed the classifier's residual
errors are **dominated by upstream column-detection and line-slicing defects**, not by
classifier thresholds. The human verifier identified five concrete geometry problems.
This phase fixes the **column-detection** half; line-slicing refinements (glyph
chopping, drop-cap handling) follow in their own phase.

Problems to fix (verifier observations + this phase's additions):

1. **Page frame/border bleeds into crops.** The rectangular rule-frame around the
   text block is partially included → OCR sees frame ink; the frame's rules also feed
   the line slicer junk lines.
2. **Marginal note numbers included.** Footnote/marginalia digits sitting outside the
   column body get pulled into the column box, widening it and confusing the slicer.
3. **The central separating line between columns is included.** Books with a vertical
   divider rule in the gutter let that rule graze the inner edge of a column box. A
   column crop must contain **no part of the central divider**.
4. **Single-column sections are split.** A full-width single-column band (a heading,
   section opener, or a genuinely single-column passage) is force-split by the
   two-column assumption, tearing the text down the middle.
5. **Single-column sections are unrecoverable as line sources.** Today the detector
   *defers* any page that isn't a clean two-column layout, so those lines are never
   sliced at all. We want to **detect, crop, and slice** single-column bands, placing
   them in the correct reading order (before the two columns they precede) and
   optionally annotating them as a header.

## What's already there (reuse, don't reimplement)

`data_prep/column_detector.detect_columns(gray)` already, on a deskewed page:
vertical-projection gutter detection; per-column dominant-run x-extent (isolated
marginalia *intended* to drop as short runs); body-bracketing horizontal-rule
detection (`_detect_rules`) for y-bounds; folio/header trim (`_trim_margins`);
confidence gating that **defers** non-two-column pages. It pads boxes **outward**
(`_PAD_FRAC`), which is part of why the frame/divider bleed in. `validate_columns.py`
already has a **no-clip edge test** (`CLIP_PX`/`GRAZE_PX`: count foreground pixels on
each box border) and IoU-vs-human-boxes — the natural home for the new gate checks.

## The core design change — a *region* model

Today a page is exactly two boxes (`column_1`, `column_2`). To support single-column
bands in reading order, a page becomes an **ordered list of regions**, each typed:

- `header`   — a full-width single-column band above the columns (often large type)
- `single`   — a full-width single-column band that is body text (not a header)
- `left` / `right` — the two halves of a two-column band

Reading order = **top-to-bottom by band; within a two-column band, left then right.**
A page is segmented vertically into bands first (does a gutter exist in this y-range?),
then each band yields its region(s).

### Artifact naming (DECIDED — migrate to `region_NN_<type>`)

Reading order today is implicit in `sorted(glob("column_*"))` (alphabetical). We adopt
explicit ordered, typed region directories:

```
data/lines/page_XXXX_auto/
  region_01_header/      line_001.png ...
  region_02_left/        line_001.png ...
  region_03_right/       line_001.png ...
  region_04_single/      line_001.png ...
```

`region_NN_<type>` sorts into correct global reading order and self-documents type.
A page that is plain two-column would be `region_01_left`, `region_02_right`.

**Downstream `column_*` consumers that must be updated** (grep-verified): 
`labeling_ui/storage.py` (`_line_numbers`, `list_lines`, `column_dir`, line-id
parsing), `data_prep/build_phase4_dataset.flatten_columns`,
`ml_vision/scripts/predict_lines.collect_page`, `data_prep/detect_nonchar_lines` &
`score_nonchar_detector` (`page_line_crops`/`_line_png`), `pipeline.crop_columns_and_lines`,
and the labeling UI's `column_{col}/line_{line}` line-id format in `app.py`/`app.js`.
This is the largest blast radius of the phase, handled by a one-shot migrator (below):
existing `column_1/2` → `region_01_left/02_right`, every glob site updated in one
commit, with a transitional back-compat read shim.

## Ground-truth capture in the labeling UI (DECIDED)

The gate's truth (gate #4) is created by a human in the existing crop view, extended
from "two draggable column boxes" to a small region-annotation tool. No APIs; writes a
new human ground-truth JSON, never the frozen dataset.

**Per page the human records:**

1. **Manual deskew by reference line.** A reference line is shown by **default in the
   upper-right corner, perfectly vertical** (a no-op 0° guide). It is **locked until the
   user clicks the "Deskew" button**, which makes its two **endpoints draggable**; the
   user aligns it to something that should be truly vertical — a frame margin, a column
   edge, or a rule. The line's deviation from exact vertical **is** the skew angle; on
   apply the page is re-rendered un-skewed by `-angle`. (Default vertical → if the user
   never touches it, the recorded angle is 0° and nothing rotates.) This is an exact,
   human-verified alternative to the automatic projection-profile estimate; the recorded
   angle becomes **deskew ground truth** (lets `validate_columns` gate the auto-deskew
   against a human number, not just self-consistency, and feeds the estimator
   improvement below). All region boxes are drawn on the un-skewed render.
2. **N regions, add/remove.** Beyond the default two column boxes, an **"+ Add single
   column"** action adds a full-width region (for headers / single-column bands); each
   region has a **type** selector (`header` / `single` / `left` / `right`). Regions are
   ordered top-to-bottom (left before right within a two-column band) — the order that
   becomes `region_NN`.
3. **Min + max box per region.** For each region the human draws **two** nested boxes:
   - a tight **`min`** box (must contain all real text ink — inside it is definitely
     text), and
   - a loose **`max`** box drawn just inside the frame / central divider / margin (the
     detected crop must not exceed it).
   The detector passes when `min ⊆ detected ⊆ max` (gate #4). The min/max pair is
   easier and more robust to author than a single "perfect" box and encodes the two
   failure modes (chopping vs frame/margin inclusion) explicitly.

Stored as e.g. `data/columns/boxes/page_XXXX.json` (extend the existing human-box
schema with `deskew_angle`, and per-region `type` + `min`/`max` rectangles). Existing
single-box human annotations remain readable (back-compat shim).

## Detection approach (image-level, no OCR, no APIs — same envelope as line_filter)

1. **Deskew** (cached, unchanged).
2. **Strip the frame.** Detect the rectangular border: near-full-height vertical rules
   near the L/R page edges and near-full-width horizontal rules near top/bottom
   (extend `_detect_rules` to both axes). Define the **text-block interior** strictly
   *inside* the frame; all subsequent projections run on the interior only, so frame
   ink can never enter a column box. (Generalizes the current top/bottom-rule logic to
   all four sides.)
3. **Band segmentation.** Within the interior, compute the horizontal projection to
   find vertical bands of text separated by clear vertical gaps. For each band,
   compute the **central-band vertical projection** and test for a gutter
   (reuse the `_GUTTER_*` logic): gutter present → two-column band; absent (dense
   across the middle) → single-column band.
4. **Per-band region boxes.**
   - Two-column band: left/right boxes split **at the gutter minimum**, then the inner
     edges pulled inward to exclude any **central divider rule** (detect a narrow
     near-full-height ink spike in the gutter; set inner edge clear of it). Verify with
     the no-clip test that no divider pixels sit on the inner border.
   - Single-column band: one full-width box (interior width).
   - **`header` vs `single` (DECIDED):** a single-column band is a `header` when its
     text is **significantly larger than the page median** — i.e. the band's median
     line height (or median glyph height) exceeds the page-wide median line height by
     a margin (e.g. ≥ ~1.5×; calibrate on labeled data). Otherwise it is a `single`
     body band. Position is *not* the criterion (a large band mid-page is still a
     header); size is.
5. **Marginalia exclusion.** Within each column's x-slice, drop short isolated
   projection runs separated from the column body (the current dominant-run idea, made
   stricter): a thin run set off by a clear gap is marginalia (footnote digits), not
   body. Validate via the no-clip test that no marginalia ink sits on a box edge.
6. **Confidence / defer.** Keep deferring genuinely ambiguous layouts
   (`confident=False`), but a clean single-column page is now **confident**, not
   deferred.

## Gate conditions (measurable, on a labeled page set)

Extend `validate_columns.py`; gate on a stratified set incl. the Phase A 17 pages +
known single-column/header/divider/marginalia pages.

1. **No frame ink in any crop.** No region box edge has > `GRAZE_PX` foreground pixels
   attributable to the frame; 0 boxes contain a frame rule.
2. **No central divider in any column.** For two-column bands, the inner edges carry
   no divider-rule ink (no-clip test on the inner border = 0 meaningful pixels).
3. **No marginalia in any crop.** Known marginal-number pages: those digits fall
   outside every region box.
4. **Region structure + min/max containment vs human annotation.** Per page, the
   detected region sequence (count + type + order) matches the human ground truth, and
   each detected box passes **`min ⊆ detected ⊆ max`** against that region's two
   human-drawn bounds:
   - **`min` box** = the tight inner bound (all real text ink). `detected ⊇ min`, else
     the crop is **cutting off characters** (FAIL).
   - **`max` box** = the loose outer bound, drawn just inside the frame / divider /
     margin. `detected ⊆ max`, else the crop is **including frame / margin / divider
     ink** (FAIL).
   Every detected edge must land in the tolerance band between the `min` and `max`
   edges on all four sides. This replaces fuzzy IoU with a crisp pass/fail that encodes
   both observed failure modes directly. Single-column bands must appear **before** the
   two-column block that follows.
5. **No-clip preserved.** The existing `validate_columns` no-clip/gutter/ink/deskew
   gates still pass (no regression to two-column pages).
6. **Deskew accuracy vs human.** On pages with a human deskew reference line, the
   automatic angle is within a small tolerance of the human angle (e.g. |Δ| ≤ ~0.2°;
   calibrate). Reported per page; the worst pages drive the estimator-improvement work.
7. **End-to-end re-measurement (the real payoff).** Re-slice the Phase A 17 pages with
   v2, re-run the **same** non-character verify harness + `score_nonchar_detector.py`.
   Target: the 3 chopped/heading false positives disappear (FP → 0) and recall does
   not regress. (This closes the loop the Phase A gate opened.)

## Verification plan

1. **Unit (synthetic):** extend `tests/test_column_slicing.py` with synthetic pages
   for each new case — full frame, central divider rule, top single-column header band,
   marginal-number column, single-column page — asserting region count/type/order and
   zero frame/divider/marginalia ink on edges.
2. **Frame/divider/marginalia gate:** `validate_columns --check regions` over the
   labeled set; 0 violations.
3. **Reading-order check:** assert flattened line order = bands top-to-bottom, left
   before right, header/single before the columns they precede.
4. **Regression:** plain two-column gold pages produce the same two boxes (now named
   `region_01_left`/`region_02_right`) with no-clip/IoU unchanged.
5. **Gate re-measurement:** the Phase A end-to-end re-run above.

## Non-interference & migration

- All new work on a dedicated worktree/branch; the frozen dataset is untouched.
- Auto vs human artifacts stay separated by `page_id` (`_auto`/`_human`); human
  transcriptions are never rewritten.
- The `region_*` rename ships via a **one-shot migrator** (mirror
  `migrate_method_tags.py`) that renames existing `column_1/2` → `region_01_left/02_right`
  and updates every glob site in one commit, with a back-compat read shim during
  transition. Keep `data/README.md` the spec source of truth.

## Decisions locked (2026-06-24)

- **Q1 — Region naming:** adopt **`region_NN_<type>/`** with a one-shot migrator and a
  transitional back-compat read shim (existing `column_1/2` → `region_01_left/02_right`).
- **Q2 — Header definition:** a single-column band is a **`header`** when its text is
  **significantly larger than the page median** line/glyph height (≈ ≥1.5×; calibrate);
  position is not the criterion.
- **Q3 — Ground truth:** authored in the **labeling UI** — N add/removable regions
  (incl. a 3rd single-column region), per-region type, **min + max boxes**, and a manual
  **deskew reference line**. Gate #4 = `min ⊆ detected ⊆ max`.
- **Q4 — `is_glyph` display-capital fix: INCLUDED here.** *(What it is: in Phase A the
  large heading `page_0560 c1/line_014` was dropped as non-character because
  `is_glyph` rejects any component spanning > 0.5 of the region as an "ornament/frame"
  — which also rejects big display capitals. Headers are full of display capitals, so
  the heading false-positive and header detection are the same problem.)* Teach
  `is_glyph` (or a sibling) to accept **large letter-like components** (stroke/aspect
  structure typical of glyphs) instead of lumping them with frames/rules, so headers
  read as text. Must not re-admit true ornament bands — validate on the Phase A labeled
  lines (the 3 FPs and the ornament-band TPs).
- **Q5 — Re-sample:** after fixes, re-slice + re-verify the **same 17 pages** for a
  clean A/B, then add a **fresh spread** weighted to divider / header / single-column /
  marginalia pages to guard against overfitting.

### Deskew: human angles feed back into the automated estimator

The manual deskew reference line is not only gate ground truth — the corpus of
human-measured angles is used to **improve the automatic deskew** (`data_prep/deskew.py`):
per page, compare auto vs human angle to (a) quantify and bound auto-deskew error as a
gated metric, (b) calibrate the estimator's parameters (search range, projection
sharpness criterion) against the human truth, and (c) surface the pages where auto
deskew is worst for targeted fixes. Goal: drive the auto-vs-human angle delta below a
small threshold so manual deskew is rarely needed.

## Still open
- **Header line-height threshold** (Q2 ≈1.5×) and the **min↔max tolerance margins** are
  to be calibrated against the first batch of human region annotations, not guessed now.
