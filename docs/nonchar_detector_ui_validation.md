# Plan — Non-Character Detector Validation via the Labeling UI

## Goal

Measure the **precision and recall** of the pre-OCR non-character line detector
(`data_prep/line_filter.py`, built on branch `nonchar-line-filter`) on
*production-like* auto-sliced pages, not just the 12 labeled/auto pages we already
have. We do this by capturing a fast human **binary ground truth** — for every
line on an auto page: *empty / non-character* vs *contains real Grabar* — through
the existing labeling UI, storing it as JSON, and scoring the detector against it.

Why this is needed (from the gap discussion): the detector has **100% precision /
21-of-30 recall** on human pages, but human pages backstop missed junk with the
empty-`ref` exclusion. On **auto pages — the real production target — the detector
is the only defense and its recall is unmeasured.** To measure recall we need a
verdict on *every* line (flagged and unflagged), which is too many lines for a
static contact sheet — hence a fast, keyboard-driven UI flow.

**No external APIs.** The entire verify flow is local: `cv2` + filesystem only. No
LLM calls, no keys, no cost. (Mentioned because the user asked to stop on any API
error — there are none on this path.)

## Gate condition

Across a stratified sample of verified auto pages (≈15–30 pages spanning page
types — see *Sampling*):

1. **Precision = 100%** — zero lines the human marks *character* are flagged
   `non_character` by the detector (no real text would be dropped). This is the
   hard gate; a single false positive is a regression.
2. **Recall reported with a decision** — measured per-page and overall. Then
   decide: if recall ≥ (threshold TBD with the data, e.g. ~0.8) **and** precision
   is 100%, promote auto-drop in production; otherwise keep the marker-only
   behavior (drop deferred) and pursue a complementary signal (position,
   OCR-confidence, repetition fallback).
3. **No regression** — the existing human transcription workflow is byte-for-byte
   unchanged; verify mode writes only the new truth JSON, never `.txt`.

Findings recorded back into this doc (per the gated-phase model).

---

## Design decisions (confirm or override)

- **D1 — Binary verdict.** Each line is `empty` (non-character: divider, ornament,
  blank/speck) or `character` (contains real Grabar). One bit. This is what the
  detector predicts, so it is exactly what we score. *Optional 3rd category* — a
  `garbage` verdict to distinguish over-segmentation specks from genuine
  ornamental dividers — is noted but **off by default** (both count as "should be
  dropped" for detector scoring). Say if you want the 3-way split.
- **D2 — Score the auto slice as-is.** The detector's recall/precision is only
  meaningful against the exact lines the *production* slicer produced. So the
  validation path **loads the existing `page_XXXX_auto` lines and verifies them**;
  it does **not** re-crop/re-slice them (that would change the lines and invalidate
  the measurement). The broader "manual crop/slice with method choice at each
  stage" UX (your fuller vision) is real but separated into **Phase B** below, and
  is not on the scoring-critical path.
- **D3 — Dedicated truth JSON, not `.txt`.** A `character` line has no
  transcription, so an empty `.txt` would be indistinguishable from an `empty`
  line. We store verdicts in a new `data/lines/<page_id>/nonchar_truth.json`,
  leaving the transcription status model untouched.
- **D4 — `storage.py` stays filesystem-only.** Per-line detector features need
  `cv2`/`data_prep`, which `storage.py` deliberately avoids. The detector verdicts
  are computed in `pipeline.py` (already imports `data_prep`) and merged into the
  lines response in `app.py`. `storage.py` only gains pure load/save of the truth
  JSON.

---

## Data model — the truth artifact (JSON)

New file per auto page, alongside its `column_*/` dirs:
`data/lines/page_XXXX_auto/nonchar_truth.json`

```json
{
  "page_id": "page_0123_auto",
  "method": "auto",
  "verified_by": "human",
  "timestamp": "2026-06-20T18:00:00Z",
  "detector": { "ink_factor": 1.6, "rule": "glyph_count==0 OR ink>1.6x page-median" },
  "lines": {
    "column_1/line_001": {
      "truth": "empty",
      "detector_nonchar": true,
      "glyph_count": 0, "ink_ratio": 2.17
    },
    "column_1/line_002": {
      "truth": "character",
      "detector_nonchar": false,
      "glyph_count": 23, "ink_ratio": 0.91
    }
  }
}
```

- `truth` = the human verdict (`empty` | `character`). The scorer's source of truth.
- `detector_nonchar` + features = the detector's verdict **at verification time**,
  snapshotted so scoring is reproducible and threshold drift is visible.
- Storing both in one record means the scorer needs only this file per page.

---

## Implementation — Phase A (scoring-critical MVP)

### A1. `labeling_ui/storage.py` — truth load/save (pure, filesystem-only)
- `nonchar_truth_path(page_id) -> Path` → `DATA_LINES/<page_id>/nonchar_truth.json`.
- `load_nonchar_truth(page_id) -> dict | None`.
- `save_nonchar_truth(page_id, verdicts, detector_meta, line_features) -> Path` —
  assembles the schema above from `{line_id: "empty"|"character"}` + the detector
  snapshot passed in. No cv2 here.
- `has_auto_lines(n) -> bool` (any `column_*/line_*.png` under `page_XXXX_auto`)
  and `nonchar_verified(page_id) -> bool` for the browser badges.

### A2. `labeling_ui/pipeline.py` — per-line detector verdicts (reuses `data_prep`)
- `line_nonchar_verdicts(page_id) -> dict[str, dict]` → for each placed line crop
  under `page_XXXX_auto`, run `data_prep.line_filter.line_features` +
  `classify_page` (the **same** module the production detector uses, so the UI and
  detector can never disagree). Returns
  `{ "column_Y/line_NNN": {non_character, glyph_count, ink_ratio} }`.
- This is cheap (~ms/line, no OCR) so verification needs no prior `predict_lines`
  run. If a `predictions.json` already carries `non_character`, prefer it for
  exact parity; otherwise compute live.

### A3. `labeling_ui/app.py` — additive endpoints (existing ones untouched)
- **Extend** `GET /api/page/{page_id}/lines`: after `storage.list_lines`, merge in
  per-line `non_character`, `glyph_count`, `ink_ratio` (from A2) and the existing
  `truth` from `load_nonchar_truth` if present. Existing consumers ignore unknown
  keys → no break.
- **Extend** `GET /api/pages` and `GET /api/pages/{n}`: add `has_auto` and
  `auto_status` ∈ {`none`, `sliced`, `verified`} so the browser can label
  auto-sliced pages. Human fields unchanged.
- **New** `POST /api/page/{page_id}/nonchar-truth` body
  `{ "verdicts": { "column_Y/line_NNN": "empty" | "character" } }` → recompute the
  detector snapshot (A2), call `storage.save_nonchar_truth`, return counts +
  confusion tallies for an instant in-UI summary. This is the *Submit empty
  markers* action.
- **New (used by Phase B, stub now)** `POST /api/pages/{n}/autoslice` → wraps
  `data_prep.auto_slice.auto_slice_page(n)` so a page with boxes but no line crops
  can be sliced from the UI.

### A4. Frontend — a "Verify non-character" mode on the label view
Reuse the existing label view (pill strip + line image + Alt+←/→ nav) with a
`state.mode = "verify"` flag, rather than a whole new view, so all the navigation
you already use carries over.

- **Entry:** from page select, an auto-sliced page shows a chip and a button
  **"Verify auto slice →"** that loads `page_XXXX_auto` lines in verify mode.
- **In verify mode:**
  - Hide the transcription textarea and the prediction box (no typing).
  - Each line starts with a verdict **seeded by the detector**: detector
    `non_character` → suggested `empty`; else suggested `character`. The human only
    *corrects* suggestions.
  - **Distinct styling for detector-flagged lines** (your spec): the pill for a
    detector-flagged line uses an "uncertain empty" look — same accent hue as the
    existing `empty` pill but **faded + dashed border + cross-hatch** (a
    `repeating-linear-gradient`), visually separating a *suggested* empty from a
    *human-confirmed* empty (solid). New CSS classes only (`.pill.suggest-empty`,
    `.pill.truth-empty`, `.pill.truth-char`); existing `.pill.*` rules unchanged.
  - **Keys:** `Alt+E` = mark empty, `Alt+C` (or Space) = mark character, `Alt+←/→`
    = navigate (all existing). A small per-line toggle button pair as well.
  - The image is the only thing you study; a glance + one key per *disagreement*
    makes a 90-line page fast since most suggestions are right.
- **Submit:** a button **"Submit empty markers"** (distinct from the transcription
  "Submit") POSTs all verdicts to A3, then shows a summary card: counts +
  TP/FP/FN/TN for this page and a link to the rolling score report.

### A5. `data_prep/score_nonchar_detector.py` — the gate report
- Read every `data/lines/*_auto/nonchar_truth.json`.
- Confusion matrix per the convention *positive = non-character*:
  TP = detector_nonchar ∧ truth empty; FP = detector_nonchar ∧ truth character
  (**must be 0**); FN = ¬detector_nonchar ∧ truth empty; TN = both negative.
- Report **precision, recall, F1** per page + overall; enumerate every **FP**
  (real text the detector would have dropped) and **FN** (junk it missed) as
  thumbnail cards (reuse the embedded-image HTML pattern in
  `ml_vision/scripts/analyze_errors.py` / `detect_nonchar_lines.py`).
- Outputs `reports/nonchar_detector_score.{csv,html,md}`. This is the gate artifact.

### A6. Sampling
- Pick ≈15–30 pages spanning page types: normal two-column prose, ornament/
  divider-heavy, section-opening pages, tables/marginalia, faint/faded scans.
  (33 pages already have auto boxes; `page_0543` source PDF is known-broken — skip.)
- Run `auto_slice_page(n)` on the chosen set to produce `page_XXXX_auto` line crops,
  then verify each in the UI and run A5.

---

## Implementation — Phase B (fuller method-choice UX, after the gate)

Your broader vision, decoupled from the measurement so it can't confound it:

- **Page browser:** auto chip on every page; show auto vs human status side by side.
- **Crop stage — method choice:** alongside the existing manual box-drawing, an
  **"Accept auto columns"** action that loads the saved `page_XXXX_auto` boxes
  (`data/columns/boxes/`) or runs the detector, one click to commit.
- **Slice stage — method choice:** **"Auto-slice"** (calls A3's `autoslice`
  endpoint) vs the existing manual **"Segment lines"**.
- This lets you choose auto or manual *at each stage independently*. Note: lines
  produced by a *manual* re-crop are **not** valid for scoring the production
  detector (D2) — the UI should label which tree the current lines came from so a
  verify session can't accidentally score hand-made lines.

---

## Non-interference safeguards

- All API changes are **additive** (new endpoints; new keys on existing
  responses). No existing endpoint signature or behavior changes.
- Verify mode writes **only** `nonchar_truth.json`. It never creates/edits `.txt`,
  so transcriptions, `empty`/`rejected` status, and the frozen dataset are
  untouched.
- Auto and human artifacts are already separated by `page_id`
  (`page_XXXX_auto` vs `page_XXXX_human`) — no cross-contamination.
- New CSS classes are namespaced; existing `.pill`/`.badge` rules unchanged.
- `storage.py` keeps its no-cv2/no-FastAPI contract (D4).

## Verification

1. **Unit:** truth round-trips through save/load; `line_nonchar_verdicts` on
   `page_0487_auto` reproduces the known flag set
   (`{c1:001,010,011,045,046; c2:001}`).
2. **UI smoke:** open `page_0487_auto` in verify mode — the 6 flagged lines show
   the suggested-empty styling, `c1/line_009` (`մութիւն։`) shows as character;
   flip a couple, *Submit empty markers*, confirm `nonchar_truth.json` written and
   the summary tallies match.
3. **Regression:** label a human page the old way — textarea, Submit/Empty/Reject,
   pills, review — all unchanged; no `nonchar_truth.json` created.
4. **Gate:** run A6 sample + A5; open `reports/nonchar_detector_score.html`,
   confirm precision = 100% (0 FP) and record recall + the promote/defer decision.

## Open questions for you

- **Q1 (D1):** binary `empty`/`character`, or add a 3rd `garbage` verdict to
  separate over-segmentation specks from genuine dividers?
- **Q2:** target recall threshold for promoting auto-drop, or decide empirically
  once we see the number?
- **Q3:** scope now — Phase A only (the measurement), or Phase A + B (the full
  method-choice UX) in one go?
- **Q4:** which pages to sample (give a list/range), or shall I pick a spread
  across the book?

---

## Build status — Phase A tooling complete (2026-06-24)

Phase A is **built and self-verified on `nonchar-line-filter`** (worktree
`.claude/worktrees/nonchar-line-filter`). The recall **measurement still needs a
human verification pass** — code is ready, the number is not yet in.

Locked decisions applied: **D1 binary** verdict (`empty`/`character`, no `garbage`
3rd class); **Q2 recall threshold decided empirically** once the number is visible;
**Q3 Phase A only** (Phase B method-choice UX deferred); **Q4 spread across the
book** (see `data_prep/sample_auto_pages.py`).

Files:
- `labeling_ui/storage.py` — `nonchar_truth_path` / `load_nonchar_truth` /
  `save_nonchar_truth` / `has_auto_lines` / `nonchar_verified` / `auto_status`
  (kept cv2-free; features passed in).
- `labeling_ui/pipeline.py` — `line_nonchar_verdicts` (reuses `data_prep.line_filter`,
  prefers a `predictions.json` `non_character` snapshot, else computes live) +
  `detector_meta`.
- `labeling_ui/app.py` — extended `/api/pages`, `/api/pages/{n}`,
  `/api/page/{id}/lines` (additive keys) + new `POST /api/page/{id}/nonchar-truth`
  returning a TP/FP/FN/TN scorecard. (The Phase-B `autoslice` endpoint was **not**
  added — sampling uses `data_prep/sample_auto_pages.py` instead.)
- `labeling_ui/static/` — verify-non-character mode on the label view: detector-seeded
  verdicts, `Alt+E`/`Alt+C`/`Space` keys, "Submit empty markers", summary card;
  new pills `.suggest-empty` (faded + dashed + cross-hatch), `.truth-empty`,
  `.truth-char`.
- `data_prep/score_nonchar_detector.py` — the gate report
  (`reports/nonchar_detector_score.{csv,html,md}`; positive = non-character; FP must be 0).
- `data_prep/sample_auto_pages.py` — slices a default book-spread of auto pages to verify.
- `tests/test_nonchar_verify.py` — truth round-trip + `page_0487_auto` detector parity.

Verified (2026-06-24):
1. **Unit** — `tests/test_nonchar_verify.py` passes: truth save/load round-trips;
   `line_nonchar_verdicts("page_0487_auto")` reproduces `{c1:001,010,011,045,046;
   c2:001}` and leaves `c1/line_009` (`մութիւն։`) as `character`.
2. **API smoke (TestClient)** — `/api/pages` carries `has_auto`/`auto_status`;
   `/lines` merges detector verdicts; `POST /nonchar-truth` writes
   `nonchar_truth.json` and returns the correct scorecard; the scorer turns it into
   a PASS report. The smoke-test truth file (detector agreeing with itself) was
   **deleted afterward** so it can't masquerade as a real human verdict.
3. **Regression** — additive-only changes; the human transcription flow
   (textarea, Submit/Empty/Reject, pills, Review) is untouched and writes no
   `nonchar_truth.json`.

**Remaining for the gate (human-in-the-loop):**
1. `uv run python data_prep/sample_auto_pages.py` to slice the spread.
2. In the labeling UI, open each sampled page → **Verify auto slice** → confirm/flip
   → **Submit empty markers**.
3. `uv run python data_prep/score_nonchar_detector.py`, open
   `reports/nonchar_detector_score.html`; confirm **precision = 100% (0 FP)**, record
   recall, and decide promote-vs-defer.

Note: `pytest` is not installed in the worktree venv (declared in `pyproject` but
unsynced), so test modules are run directly as scripts (they expose plain `test_*`
functions for pytest when available). *(Resolved 2026-06-24: `uv sync --extra dev`
installs pytest 9.1.0; full suite is green.)*

---

## Gate result — Phase A FAILED (2026-06-24)

Human verification completed over **17 auto pages / 1326 lines**:

| Precision | Recall | F1 | TP | FP | FN | TN | Gate |
|---:|---:|---:|---:|---:|---:|---:|:--|
| **92.7%** | 70.4% | 80.0% | 38 | **3** | 16 | 1269 | **FAIL** (hard gate = 0 FP) |

The 3 false positives are all `glyph_count==0` lines that are actually text
(thin/degraded text and a large display heading), so **auto-drop is NOT promoted** —
the detector stays marker-only. The errors are dominated by **upstream slicing /
column-detection defects** (chopped glyphs, display-capital handling, page borders,
marginal numbers, single-column splits), not by classifier thresholds.

**Full analysis, the verifier's observations, and the proposed next phase are in
[`slice_categorization_findings_and_next_steps.md`](slice_categorization_findings_and_next_steps.md).**
