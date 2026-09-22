# Phase 7 — Gemini-flash vision correction of Grabar OCR

**Status:** planned (POC validated 2026-07). **Owner:** —
**Depends on:** Phase 5 (LLM text-correction), Phase 6 (column detection), the promoted
`corpus/`. **Supersedes** the abandoned "drop garble lines as non-character" idea
(`corpus/ERRATA.md` E2).

## Motivation

The committed corpus (`corpus/book.grabar.md`) was transcribed with **baseline Tesseract**,
then text-only LLM correction (`gemini-3.1-pro` minimal-edit). Two failure classes remain,
both discovered while reviewing `corpus/`:

1. **Display / heading fonts are badly mis-read.** The title page p453 came out as
   `ԱՍՌԱՋԶԻՆՀԱՏՈՐԸek` (for ԱՌԱՋԻՆ ՀԱՏՈՐ), `nnn19011IeS5` (for 1915), etc. Text-only
   correction can't fix this — it never sees the image.
2. **Real text vs. noise is indistinguishable from the OCR string alone.** Tesseract emits
   gibberish both for genuine ornamental dividers (drop) *and* for legible text it simply
   failed on (must recover). Only the **image** separates them (`corpus/ERRATA.md` E2). This
   is why an automatic text-heuristic drop filter was rejected — it would delete the volume
   title, "1915", prayers, etc.

**Insight:** a single **vision** pass fixes both. Give a frontier VLM the line-crop image +
the candidate OCR; it returns the corrected Grabar, or a sentinel for a no-text slice.

## POC result (this is the gate evidence, already collected)

Script: `build/vision_correct_poc.py` (per-line: image + candidate OCR → corrected Grabar or
`[NON-CHARACTER]`). Model: `gemini-3.5-flash`. Pages: **p453** (display) + **p519** (Bolorgir
body).

- **Quality:** near-perfect letter recovery on **both** display and body type; matched the
  hand-verified p453 reference (`corpus/book.grabar.corrected.md`); correctly returned
  `[NON-CHARACTER]` for ornamental dividers; fixed leading-glyph stutters, a bled `)`, and
  tone-code `գ3→գձ`.
- **Cost:** ~**$0.002/line** → **~$28 for the whole 13,873-line corpus** at per-line
  granularity. A **whole-column image per call** (one call ~= a page) cuts image tokens ~10×
  → est. **$3–5 total**.
- **Caveat (the one real problem to solve):** the exact **punctuation/spacing convention** of
  the print is not reproduced reliably — the model adds/removes spaces around `. ։ ,`, and
  sometimes renders `։` as `:`. Tightening the prompt swung it to the opposite error
  (dropping needed spaces). **Letters/content are reliable; spacing is not.** Fix with a
  deterministic normalization post-step and/or a 1–2 line few-shot exemplar, not prompt
  wording alone.

## Design

Add a new **OCR-correction variant** (a `correct` stage tag), parallel to the existing
`tesseract_llm_gemini_minimal-edit`, e.g. tag **`tesseract_vlm_g35flash`**. It reads the same
baseline predictions + the line/column images and writes a `predictions.json` in the same
schema, so the rest of the pipeline (collect_rows → lines.json → promote) is unchanged.

### Reuse (do not reinvent)
- **Gemini client + pricing:** `ml_vision/scripts/llm_correct.py` — `call_gemini`,
  `MODELS["gemini-3.5-flash"]`, `PRICE_PER_MTOK`, `GEMINI_THINKING_BUDGET`, `_retry`,
  `MAX_TOKENS`. Auth: `GEMINI_API_KEY` (in `.env`). Extend `call_gemini` to accept image
  Parts (`genai_types.Part.from_bytes(data=png, mime_type="image/png")` in `contents`).
- **Stage wiring:** mirror `pipeline/stages.py::correct_llm` (line 78) + `registry.py` +
  `config.py::StageSpec`; the digitizer pattern is `ml_vision/scripts/digitize_page.py`.
- **Prediction store:** `data/predictions/<tag>/page_XXXX/predictions.json`, lines keyed by
  `region_NN_type/line_NNN` → `{pred_beam, ...}`. Images:
  `data/lines/page_XXXX_*/<region>/line_NNN.png` (per-line) and
  `data/columns/page_XXXX_*_region_*.png` (per-column).
- **non_character:** the sentinel `[NON-CHARACTER]` maps to `non_character: true` in
  `collect_rows` (`orchestrator.py:133`); the corpus already drops flagged lines
  (`corpus.py:210,268`). This replaces the image-only `line_filter` detector for these lines.
- **Promote:** `python -m pipeline.promote --range 453-641 --from … <run-with-new-tag>`.

### Two batching modes (decide by cost vs. alignment risk)
- **A. Per-line crop** (POC default): simplest, robust alignment, ~$28. Start here.
- **B. Per-column image, numbered output**: send the whole column PNG once, ask for
  `<n>\t<grabar>` per source line, parse like `llm_correct.parse_rewrite`. ~10× cheaper
  (~$3–5) but needs line-count alignment guards (fall back to per-line on mismatch).

### Prompt
Base it on `build/vision_correct_poc.py`'s `SYS`. Must specify: output only Grabar (no
translation/brackets), correct OCR errors, **preserve exact Armenian punctuation `։ ՝ ՞ ՛ ՚`
and normal single spacing (no spaces around punctuation, no inter-letter spaces)**, and emit
`[NON-CHARACTER]` for no-letter slices. Add a **1–2 line few-shot** showing the exact target
spacing to pin the convention. Follow with a deterministic normalizer (collapse spaces before
`. , ։`, restore `։`, strip inter-letter single spaces on all-caps display lines).

## Gate condition (measurable — must pass before adopting corpus-wide)
On the labeled/gold pages (see `data/golden/`, `data/frozen_test_set/`, `reports/phase_4_*`):
1. **CER ↓ vs. baseline Tesseract** and vs. `tesseract_llm_gemini_minimal-edit` on the same
   lines (jiwer via `pipeline/scoring.py`). Target: material reduction, esp. on display/heading
   lines.
2. **Noise handling:** `[NON-CHARACTER]` precision/recall vs. the human `nonchar_truth.json` —
   **0 real-text lines dropped** (the repo's standing bar), recall ≥ the current image detector.
3. **Cost** within budget (measured; expect $3–28 one-time).
Record all numbers in `docs/ocr_approach_comparison.md` (the comparison file).

## Build steps
1. Extend `call_gemini` (or a thin `call_gemini_vision`) to accept image parts + text.
2. Write the vision corrector (new `data/predictions/tesseract_vlm_g35flash/…`), mode A first;
   reuse retry/pricing/usage accounting from `llm_correct.py`.
3. Add the deterministic punctuation normalizer + few-shot; iterate against p453/p519.
4. Register as a `correct` stage tag; run a small page set (the gold pages) → score → fill the
   comparison file.
5. If the gate passes, run over 453–641, then `pipeline.promote` to refresh `corpus/`.
   (Try mode B for the full run to cut cost; keep mode A as the alignment fallback.)

## Verification
- Re-run `build/scan_defects.py` on the refreshed corpus: `g_noise`/`g_flagged` should drop
  sharply and `g_flagged` should now be non-trivial (lines correctly marked non_character).
- Spot-check p453/p519 in `corpus/book.grabar.md` against the images.
- Confirm `corpus/book.english.md` is unchanged (translation stage untouched).

## Risks
- **Line/column mis-alignment** in mode B → guard with per-line fallback.
- **Punctuation drift** → the normalizer + few-shot; keep the human `book.grabar.corrected.md`
  as the authority for any page where it disagrees.
- **Hallucinated "corrections"** (model inventing plausible Grabar not in the image) → the gate's
  CER check on labeled lines catches this; keep `thinking_budget` low and temperature default.
- **Cost creep** if run per-line at scale → prefer mode B once validated.

## See also
- `corpus/ERRATA.md` E2 (the defect + decision trail), E4 (p453 hand-reference).
- `docs/ocr_approach_comparison.md` — where results go, to compare this vs. the alternatives.
- `docs/phase_4_generalization.md`, `docs/phase_3_trocr_finetune.md` — the TrOCR fine-tune
  alternative (data-limited; the fallback if vision correction underperforms or costs too much).
