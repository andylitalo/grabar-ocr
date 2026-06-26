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

---

## Implementation findings (2026-06-25)

Commits 1–4 landed on `phase6-column-detection`. Region model + migrator (C1),
UI annotator (C2), `detect_regions` + `is_glyph` fix (C3), and the
`validate_columns --check regions` gate + calibration (C4) are built and tested.
13 pages were human-annotated (min/max + deskew) across the stratified set.

### Calibrated thresholds (fit to the 13-page batch, not guessed)
- **Frame rule**: `_RULE_FRAC = 0.70` (a rule spanning the text block is ~0.78 of
  full page width; text rows are ~0.4). `_FRAME_INSET_FRAC = 0.004` clears the
  rule's anti-aliased edge from the interior.
- **`is_glyph` display capital**: `_MIN_DISPLAY_CAP_PX = 30`, extent ∈ [0.20, 0.70]
  — cleanly separates page_0560's 48–54px heading caps from the ≤20px ornament
  flecks (validated: heading glyph 0→13, 0 ornament re-admits, 0 real-text loss).
- **Header**: `_HEADER_HEIGHT_MULT = 1.5×` page-body median line height.
- **Gate #4 containment (asymmetric)**: `det ⊇ min` within **15px** (clipping is the
  real risk; worst clean underrun 12px), `det ⊆ max` within **55px** (the detector
  keeps a little more clean margin than the annotator's tight max; worst overrun
  45px; the 0-frame-edge gate is the real frame guard).
- **Gate #6 deskew**: `|auto − human| ≤ 0.35°` (worst residual 0.32°, page_0080).

### Gate results
- **No regression**: old `--check columns` PASSES on all 10 gold pages;
  `--check deskew` PASSES; 21 unit tests pass.
- **`--check regions`: 7/13 PASS** — every clean two-column page with intact rules
  (0040, 0080, 0120, 0201, 0241, 0281, 0321). The y-trim (folio/running-header
  bracketing) + gutter-valley split + frame strip carry these.
- **6 fail, all genuine harder layouts** (not threshold issues):
  - `0160` — **broken/dashed bottom rule** (the same degraded rule Phase A flagged)
    slips under `_RULE_FRAC` and leaks onto the box edge.
  - `0520 / 0560 / 0640` — **header fused to the columns with no whitespace gap**;
    band segmentation can't peel it, so the structure differs (and 0560/0520 defer
    as "unbalanced"). Needs a **gutter-extent / header-peel** step: within a band,
    find where the gutter begins vertically and split the full-width top as a
    header/single sub-band.
  - `0522` — a small centred text block; the projection grabs the whole interior.
  - `0523` — three stacked single bands; detector finds one.

### Gate #7 (the FP→0 payoff) — NOT yet achieved; honest status
The `is_glyph` fix is **necessary but not sufficient** for page_0560:
- On the existing auto slice the heading now reads **glyph=13** (was 0) — the glyph
  trigger is gone — **but `ink_ratio = 1.63 > 1.6`, so the independent high-ink
  rule still flags it non-character.** (The findings doc predicted exactly this.)
- `detect_regions` currently **defers** page_0560 (sandwiched/overlapping header →
  "two-column band unbalanced"), so it isn't cleanly re-sliced either.
Eliminating the page_0560 FP therefore needs **both**: (a) the header-peel so the
heading is sliced as its own region, and (b) handling the bold-heading high-ink
case (e.g. exclude detected `header`/`single` text regions from the ornament
ink-rule, or compute the ink median per region). The full 17-page re-measurement
additionally needs a **human re-verify pass on the re-sliced pages** (re-slicing
changes line ids, so the old `nonchar_truth.json` can't be reused).

### Recommended next steps
1. **Header-peel** (gutter-extent split) — unlocks 0520/0560/0640 structure and is
   the prerequisite for the page_0560 payoff.
2. **Ink-rule × region type** — don't apply the ornament high-ink rule to `header`
   regions (or use a per-region median), to clear the page_0560 heading FP.
3. Re-slice the 17 Phase A pages, **human re-verify**, re-run
   `score_nonchar_detector.py` for the real FP→0 number.
4. Optional: degraded/broken-rule handling (0160), small-block single (0522).
5. Run `data_prep/migrate_region_names.py --execute` as the real-data cutover once
   Phase 6 is the active reader (deferred; back-compat covers the interim).

## Follow-up findings (2026-06-25, part 2)

### Step 2 (ink-rule × region type) — DONE
`line_filter.classify_page` no longer applies the ornament high-ink half of the
rule to `header` regions. The region type is parsed from the line-id's leading
segment (`region_NN_<type>/line_NNN`) by a local regex (`region_type_of`), so the
filter stays dependency-free and the exemption is automatic wherever region-tagged
ids flow. `glyph_count == 0` still applies to every region (a blank/rule line in a
header is still caught); legacy `column_N` ids carry no type and are never exempt,
so existing slices are unchanged. New unit tests in `tests/test_nonchar_verify.py`
cover the parser, `is_high_ink` exemption, and `classify_page` (header dense line
kept, blank header line flagged, body ornament flagged); the page_0487 parity test
is unchanged. This is gate #7 mechanism **(b)** — but it only bites once page_0560
is re-sliced so its heading lives in a `region_NN_header/` dir (the existing
`nonchar_truth.json` keys are legacy `column_N`, which are not exempt by design).

### Step 1 (header-peel) — attempted, NOT shipped; projection/CC heuristics are insufficient
Looked directly at the three pages (renders in the worktree): the "headers" are
**heterogeneous and hard**, not clean full-width bands:
- **0640** — a *centered* multi-line heading atop clean two columns; the title line
  is narrow, the subtitle wider, separated from the body by only a small gap (so
  `_segment_bands` fuses it into the two-column band).
- **0560** — a centered title **plus a large display letter**, *sandwiched* between
  two two-column bands and bounded by mid-page horizontal rules; the heading's own
  inter-line gaps shatter it into several `_segment_bands` pieces.
- **0520** — a *chapter-ending* centered title embedded in the **lower-left column**
  with an ornament flourish; not a page-spanning band at all (the human boxed it
  generously to full width).

Six distinct discriminators were prototyped against all 13 annotated pages (kept in
the session scratchpad, not committed): (1) wide central gutter strip; (2) windowed
"two-column test failed ⇒ full"; (3) positive single run spanning >0.7·w across
center; (4) central-gutter-point occupied (`gval`); (5) central-band channel-min
occupied; (6) narrow gutter-x strip occupancy; (7) connected-component per-line
gutter-gap classification. **Every one either missed the centered headers or
false-positived on the 7 clean two-column gold pages** — because in real Bolorgir
two-column text the gutter is not clean (punctuation/ascenders poke in, the gutter
wanders), and the headers are centered/narrow rather than edge-to-edge, so no 1-D
projection or per-line gutter test separates the two without unacceptable regression
risk. Shipping such a heuristic would violate the gated rule ("building ahead of
validation obscures where the real problem is"), so **nothing was changed in
`column_detector.py`** and the region gate stays 7/13 (no regression; old `--check
columns` still PASS on all 10 gold pages).

**Conclusion:** header-peel needs a different primitive than projections — most
likely connected-component **text-line grouping with an explicit column model**
(fit the two-column gutter from the confidently-two-column rows, then mark lines
whose glyph clusters straddle that fitted gutter as header/single), and probably a
few more annotated header pages to calibrate. That is a detector redesign with its
own regression surface, beyond follow-up polish — flagged for an explicit go/no-go
rather than started silently.

### Gate #7 (FP→0) status after this round
Mechanism (b) is in place; mechanism (a) is **blocked** on the header-peel above.
So page_0560's heading FP is not yet measurably zero: with the page still sliced
under legacy `column_N` ids (no `header` type), the exemption can't fire, and the
detector can't re-slice 0560 into a header region. The honest path to the real FP→0
number is unchanged from step 3 — but it now depends on either (i) the CC-based
header-peel landing, or (ii) a deliberate decision to re-slice only the pages whose
headers the detector already separates and re-verify those. No number is claimed.

## Workflow decision (2026-06-26): crop two-column pages well, defer the rest

After the header-peel negative result, the scope was set explicitly: **auto-slice
clean two-column pages well, and route every divergent page to manual region
annotation.** Detecting "is this a clean two-column page?" is far easier than
segmenting a header, and the error asymmetry is decisive — a wrongly-deferred clean
page costs one human annotation; a wrongly-sliced divergent page silently corrupts
data. So the detector is tuned to **defer on any doubt**, and `auto_slice` already
embodies this (it keys on `detect_columns`: confident ⇒ crop, else defer + log).

**Two detector hardenings (commit "safe auto-slice workflow"):**
- **Two-column purity guard.** The one false-confident case was page_0640 — a header
  fused atop the columns (no whitespace gap) was sliced as plain two-column, swallowing
  the header. A full-width band fused into a two-column region crosses the gutter,
  leaving a long contiguous ink run; clean gutters show only short pokes (≤ 0.25×
  the body line height across the 9 gold pages) while 0640 measures **9.8×**. When
  the run exceeds `_GUTTER_PURITY_MAX_LH` (0.6) the page defers. A genuine central
  divider rule is excluded from the measurement first, so it never trips the guard.
- **Edge-rule trim.** page_0160's degraded/dashed bottom rule has mean ink below
  `_RULE_FRAC` (so the average-ink detector misses it) but a long contiguous run on
  the box edge (0.82). A final pass trims any such rule off a box's top/bottom edge —
  monotonic, capped at 4 % of box height, a no-op on clean edges.

**Gate reframed** (`validate_columns --check regions` → the *auto-slice gate*): mirrors
production. PASS = **no divergent page is auto-sliced** (MIS-SLICE) AND **every
auto-sliced page reproduces the human two-column boxes** (min ⊆ det ⊆ max, no clipped
glyphs, no frame/divider edge ink, deskew in tol). Deferral is a valid outcome, never
a failure; `detect_regions` is shown only as a hint for the annotator.

**Result — gate PASSES 13/13 annotated pages:** 8 auto-sliced OK (the 7 clean pages +
0160), 5 safely deferred (0520, 0522, 0523, 0560, 0640), **0 mis-slices**. Deskew +
column gates unchanged (PASS); 26 unit tests pass (incl. fused-header-defers and
edge-rule-trim).

**Operational loop:** `auto_slice --report <csv>` writes every page's status and
prints the deferred worklist (`Needs manual region annotation: …`); the human opens
those in the labeling UI and annotates regions. Clean pages are sliced headlessly.

## Stock-taking at merge (2026-06-26)

Data migrated to the region convention: `migrate_region_names.py --execute` moved
126 dirs/PNGs (`column_N → region_NN_<type>`) and repointed 49 prediction/nonchar
JSON files; reversal log in `data/backups/`. Idempotent; 26 unit tests + all three
gates PASS on the migrated data.

**Problems RESOLVED:**
- *False-confident mis-slice (page_0640)* — a header fused atop the columns was
  sliced as plain two-column, swallowing the header. The purity guard now defers it.
  This was the only page in the annotated set that the detector got silently wrong.
- *Rule on the crop edge (page_0160)* — a degraded/dashed bottom rule sat on the
  left column's bottom edge (would feed a junk "line" to OCR). The edge-rule trim
  removes it (measured edge run 0.69 → 0.00).
- *Gate semantics* — the region gate counted safe deferral as failure (7/13). Reframed
  as the auto-slice gate; now PASS 14/14 (9 auto-sliced OK, 5 deferred, 0 mis-slices).
- *Divergent layouts in general* (single-column 0522, stacked singles 0523, sandwiched
  header 0560, bottom-chapter-title 0520) — all safely deferred to manual annotation
  rather than mis-cropped.
- *Non-character heading glyph trigger (page_0560)* — the `is_glyph` display-capital
  fix (glyph 0 → 13) and the header ink-rule exemption are both in place.
- *Id convention* — legacy `column_N` migrated to ordered/typed `region_NN_<type>`.

**Problems UNRESOLVED / deferred (and why it's acceptable):**
- *Header auto-cropping (0520/0560/0640)* — not solved; documented negative result.
  Not required by the chosen workflow (these pages are hand-annotated). Only needed if
  we later want headers sliced headlessly → CC-redesign go/no-go.
- *Gate #7 FP→0 as a measured number* — the page_0560 heading FP persists because the
  page DEFERS (its heading stays in `region_01_left`, so the header ink-exemption can't
  fire). Closing it needs either header-peel, or a human to annotate 0560's header
  region in the UI and re-verify. Mechanisms are in place; the number is not claimed.
- *Push to origin* — branch is unpushed; awaits authorization.

### Open / next
- Optionally annotate the 5 deferred pages in the UI to grow the region ground-truth.
- Header-peel CC redesign — go/no-go, only if headless header cropping is wanted.
- `git push` the branch when ready.
