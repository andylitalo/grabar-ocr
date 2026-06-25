# Slice Categorization — Phase A Findings & Next Steps

*Recorded 2026-06-24, after the human verification pass over 17 auto-sliced pages.*
*Companion to `nonchar_detector_ui_validation.md` (the build plan). This file closes
out the **investigation** into whether we can auto-drop non-character lines, records
the human's observations, and proposes the next phase.*

---

## TL;DR — the gate FAILED, and the cause is mostly upstream

| Metric | Value | Gate |
|---|---|---|
| Pages verified | 17 (`page_0040_auto` … `page_0640_auto`) | — |
| Lines verified | 1326 | — |
| **Precision** | **92.7%** (3 false positives) | **FAIL** — hard gate is 100% (0 FP) |
| Recall | 70.4% (16 false negatives) | reported |
| F1 | 80.0% | — |
| TP / FP / FN / TN | 38 / 3 / 16 / 1269 | — |

**Decision now: do NOT promote auto-drop.** Three false positives means auto-drop
would delete *real text*. The detector stays **marker-only** (flag, never delete)
until the upstream slicing/column problems below are fixed and we re-measure.

**Why this is a slicing problem, not a threshold problem.** All 3 false positives
are `glyph_count == 0` lines that are actually text. No `ink_factor` tuning fixes
that — the page never produced glyph-like components for those lines, because the
*slicer chopped the characters* or the *glyph discriminator rejects display
capitals*. The non-character classifier is necessary but **not sufficient**; its
residual errors are dominated by defects one and two stages upstream.

---

## Per-page scores

| page | P | R | FP | FN | note |
|---|---:|---:|---:|---:|---|
| page_0040_auto | 100% | 50% | 0 | 1 | speck missed |
| page_0080_auto | 67% | 67% | **1** | 1 | thin real text dropped + drop-cap missed |
| page_0120_auto | — | — | 0 | 0 | no non-char lines |
| page_0160_auto | 100% | 33% | 0 | 2 | broken rules missed |
| page_0200_auto | 100% | 20% | 0 | 4 | specks/accent fragments missed |
| page_0240_auto | 100% | 100% | 0 | 0 | clean |
| page_0280_auto | 100% | 50% | 0 | 2 | drop-cap + fragment missed |
| page_0320_auto | 100% | 83% | 0 | 1 | drop-cap missed |
| page_0360_auto | — | — | 0 | 0 | no non-char lines |
| page_0400_auto | 100% | 100% | 0 | 0 | clean (matches earlier anchor) |
| page_0440_auto | **0%** | — | **1** | 0 | thin real text dropped |
| page_0480_auto | 100% | 67% | 0 | 1 | fragment missed |
| page_0486_auto | 100% | 71% | 0 | 2 | |
| page_0487_auto | 100% | 100% | 0 | 0 | clean (matches earlier anchor) |
| page_0560_auto | 80% | 80% | **1** | 1 | large heading dropped |
| page_0600_auto | 100% | 100% | 0 | 0 | clean |
| page_0640_auto | 100% | 50% | 0 | 1 | |

(page_0520 self-deferred at slice time — low-confidence layout — so it is not scored.)

---

## The errors, grounded in the actual crops

### False positives — real text the detector would have DROPPED (the hard-gate failures)
All three are `glyph_count == 0`. The `glyph_count == 0` rule is the sole source of
every false positive.

- **`page_0560_auto column_1/line_014`** (glyph 0, ink 1.63×) — "ԵՕԹՆԵՐԵԱԿ ՀՈՈՎ",
  a **large stylized section heading**. `is_glyph` rejects each big bold letter
  because it "spans much of the region" (`cw > 0.5·col_w or ch > 0.5·col_h`) — the
  same rule that filters ornaments/frames also filters display capitals. So a real
  heading reads as zero glyphs and (being bold) trips the high-ink rule too.
- **`page_0080_auto column_1/line_009`** (glyph 0, ink 0.42×) — short, thin, italic-ish
  real text + a section marker; no connected component passes `is_glyph`.
- **`page_0440_auto column_2/line_003`** (glyph 0, ink 0.42×) — same archetype as 080.

### False negatives — non-character junk the detector MISSED
Two sub-families, both slipping *between* the two rules (glyph>0 and ink<1.6×):

- **Broken / degraded horizontal rules.** `page_0160_auto column_1/line_001`
  (glyph 10, ink 1.49×): a dashed rule fragments into ~10 small components, so
  `glyph_count==0` doesn't fire, and ink sits just under 1.6×. Also
  `page_0160 c2/036`, `page_0200 c2/037`, `page_0486 c2/046`, `page_0640 c2/045`.
- **Over-segmentation specks / accent fragments.** `page_0200_auto column_1/line_028`
  (glyph 1, ink 0.09×): a near-blank crop with a single curved mark. Also
  `page_0200 c1/022,028,029`, `page_0040 c2/028`, `page_0480 c2/011`,
  `page_0560 c1/023`, `page_0486 c1/015`.
- **Drop-caps / display openers** appear in both columns at `line_001`
  (`page_0080 c2/001`, `page_0280 c2/001`, `page_0320 c1/001`) — partially-cut large
  initial letters that read as a couple of glyphs.

---

## The human's observations (raw notes from the verification pass)

**Line slicing**
1. **Chopped characters → false "empty".** Slicing sometimes sliced off part of the
   characters in a line, so the classifier predicted the line was empty/non-char
   when it was really just characters that were hard to recognize.
   → *maps to FPs `page_0080 c1/009`, `page_0440 c2/003` (glyph 0 real text).*
2. **Partial cuts of large stylistic letters → false "real".** Fragments of big
   decorative letters (drop caps / display capitals) were sometimes classified as
   real letters. → *maps to FNs at `line_001` and the heading FP `page_0560 c1/014`.*

**Column cropping**
3. **Borders included.** Some column crops included the page border/frame. This will
   likely confuse the OCR later, and the frame's rules also feed the slicer junk.
4. **Marginal note numbers included.** Some crops pulled in numbers/notes sitting
   outside the column margins, which appears to confuse the slicer.
5. **Single-column sections split.** Some pages have single-column sections; cropping
   them into two columns splits the text down the middle.

---

## Root-cause synthesis — two layers

**Layer 1 — upstream geometry (column detection + line slicing).** This is where
most of the damage originates:
- Column detector includes the page frame/border (obs. 3) and marginal note numbers
  (obs. 4), and assumes exactly two columns (obs. 5).
- Line slicer chops glyphs (obs. 1) and mishandles tall display rows / drop caps
  (obs. 2), producing both "empty-looking" real lines and stray fragments.

**Layer 2 — the classifier / `is_glyph` discriminator.** Given clean input it is
fine, but it is miscalibrated at the extremes:
- `is_glyph` rejects **large display capitals** as ornament/frame → real headings
  dropped (FP). 
- `glyph_count==0` drops **thin/degraded real text** (FP).
- **Broken rules** fragment into many components and miss the high-ink cut (FN).
- **Specks** (glyph≤1, tiny ink) fall outside both rules (FN).

**Conclusion:** the binary image-level detector cannot reach 100% precision while
Layer 1 keeps feeding it chopped text and heading capitals. Fixing thresholds in
Layer 2 alone trades FPs for FNs and back. The investigation should be **closed as
"blocked on upstream slicing/column detection,"** and the next phase should pivot up
the pipeline.

---

## Proposed next steps

### Immediate (no new work)
- Keep the detector **marker-only**; auto-drop stays deferred. Human-page flow is
  unaffected (empty-`ref` exclusion still backstops there).

### Option A — Fix upstream geometry first, then re-measure *(recommended)*
The errors trace to column detection and line slicing, so fix those and re-run the
*exact same* Phase A verification harness (it's built and reusable):
- **Column detector:** detect and strip the page frame/border; detect and exclude
  marginal note-number columns; detect single-column pages (and don't split them).
- **Line slicer:** stop chopping glyph tops/bottoms; give tall display rows / drop
  caps their own handling so they aren't fragmented.
- Then `sample_auto_pages.py` → verify in UI → `score_nonchar_detector.py`. If the
  upstream fixes alone drive FP→0 and lift recall, the detector may pass unchanged.

### Option B — Harden the classifier in place (interim band-aid)
Useful only to stop the *worst* outcome (dropping real headings) before A lands:
- **Rescue display capitals:** a `glyph_count==0 AND high-ink AND tall` line is a
  heading, not an ornament band — reclassify as text. (Risk: must not also rescue
  true ornament bands; needs a discriminating feature, e.g. vertical-stroke count.)
- **Catch broken rules:** flag rows that are many *wide, thin, horizontally-aligned*
  fragments spanning the column width (recovers the dashed-rule FNs).
- **Catch specks:** flag `glyph≤1 AND tiny ink AND short height` crops.
- Caveat: these are patches around upstream defects and can reintroduce FPs.

### Option C — Reframe to multi-class line categorization
Replace binary char/non-char with a small taxonomy — `text`, `heading`, `drop_cap`,
`ornament/divider`, `border`, `margin_number`, `speck`. This both improves routing
(headings → OCR; ornaments/specks → drop; border/margin → signals the *column crop
was wrong*) and turns the detector into a diagnostic for the Layer-1 fixes. Larger
effort; natural successor to A.

**Recommendation:** Option A as the next phase, carrying the *heading-rescue* slice
of B immediately (dropping a real heading is the worst single failure). Treat the
non-character detector as validated-but-blocked, not broken.

---

## Decisions locked (2026-06-24)

- **Next phase = column detection first** (strip page frame/border, exclude marginal
  note numbers, detect single-column pages). It is the upstream root that feeds
  borders + margin numbers into the slicer and splits single-column text.
- **Heading-rescue patch: REJECTED — do not apply.** Criterion was "apply only if it
  strictly improves the 17 labeled pages without breaking anything." Tested
  empirically: **no robust rule exists.**
  - Page-relative height fails: `page_0560`'s normal text is large too, so the 62px
    heading is only ~1.5× its page median and collides with a true ornament band at
    1.73×.
  - The heading is image-feature-indistinguishable from ornament bands: `glyph==0`
    (because `is_glyph` rejects big/wide components), high-ish ink, ~10–13 components
    — the same signature as the `line_001` divider/ornament true-positives.
  - The *only* separating rule on these pages is an ink micro-band (heading 1.63× vs
    nearest true ornament 1.75×, just 0.03× above the 1.6× threshold) — a 0.12×
    margin fit to a single example that would create new false positives on
    unlabeled pages. Technically "strictly improves" the 17 pages, but only by
    overfitting, so it fails the intent of the criterion.
  - **Real fix lives upstream/in `is_glyph`:** teach the glyph discriminator to
    recognize large *display capitals* (letter-like stroke/aspect structure) instead
    of lumping them with ornaments/frames. Folded into the next phase, not patched now.
  - The other 2 false positives (`page_0080 c1/009`, `page_0440 c2/003`) are
    chopped/thin normal-height text — a pure *slicing* artifact, also deferred to the
    upstream phase, not classifier-fixable without risking blank-speck FPs.

## Still open for you
- **Re-sample or reuse?** After upstream fixes, re-slice + re-verify the *same* 17
  pages (cleanest before/after), or draw a fresh spread? (Leaning: reuse the 17 for a
  clean A/B, then add a fresh spread to guard against overfitting to them.)
