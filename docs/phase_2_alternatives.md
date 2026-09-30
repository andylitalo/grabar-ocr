# Phase 2 — Alternatives Analysis: VLM APIs vs TrOCR Fine-Tuning

**Date:** 2026-04-14
**Status:** Research complete — decision pending benchmark results

---

## Summary

Before committing to TrOCR fine-tuning, three alternative approaches are worth evaluating. The user observed that Gemini's console already recognizes some Armenian characters from raw PDFs — this is the key signal that frontier VLMs may be viable as a drop-in replacement for a fine-tuned OCR model.

---

## Candidate Approaches

### 1. Frontier VLM Zero-Shot / Few-Shot (Tier 1 — Immediate)

**Models:** Gemini 2.0 Flash, GPT-4o, Claude Haiku 3.5

All three accept image inputs and output Armenian Unicode natively. No training data required. A carefully crafted prompt instructs the model to act as a paleographer and output Bolorgir transcription in Armenian Unicode.

**Zero-shot prompt template:**
```
You are an expert paleographer specializing in Classical Armenian (Grabar) manuscripts.
The image shows a single line of text in Bolorgir script — a printed calligraphic style
used in Armenian liturgical books from the 17th–19th centuries.

Transcribe the text exactly as written, using Armenian Unicode (U+0531–U+058F).
Output ONLY the Armenian text. Do not transliterate. Do not expand abbreviations.
Use ՚ (U+055A) for elision marks. Use ։ (U+0589) for full stops.
```

**5-shot variant:** Prepend 5 example image+transcription pairs from the Phase 0 golden set.

**Expected CER:** Unknown for Bolorgir specifically. Given the user's console observation: likely 20–60% zero-shot, 10–40% with 5-shot. Either is dramatically better than TrOCR's 93.4% baseline.

**Cost at scale (9,000 lines = 30L × 300 pages):**

| Model | Per line | Total (9k lines) |
|-------|----------|------------------|
| Gemini 2.0 Flash | ~$0.0001 | **~$0.90** |
| gpt-4o-mini | ~$0.0002 | **~$1.80** |
| Claude Haiku 3.5 | ~$0.0007 | **~$6.30** |
| Gemini 1.5 Pro | ~$0.002 | **~$18** |
| GPT-4o | ~$0.004 | **~$36** |
| claude-sonnet-4-5 | ~$0.005 | **~$45** |

**Infrastructure change if VLMs win:** Replace TrOCR BentoML endpoint with an async API client. Eliminates GPU dependency for OCR entirely — repurpose RTX 3090 for layout detection only.

**Throughput:** Gemini 2.0 Flash at 2000 RPM → 9,000 lines in ~4.5 minutes.

---

### 2. Transkribus (Tier 2 — Low Effort, Specialized)

Transkribus is a platform specifically designed for historical document HTR (Handwritten Text Recognition). Key advantages over TrOCR for this use case:

- **Low-data training:** Transkribus's PyLaia-based HTR engine can fine-tune on **75–150 lines** (vs. TrOCR's need for hundreds to generalize). Our 34 Phase 0 lines are close to sufficient for a first training run.
- **Community models:** The Transkribus public model library contains at least 1–3 community-trained Armenian HTR models (Bolorgir-adjacent) as of mid-2025. These can be tested at zero cost before any training.
- **Free tier:** Allows a meaningful evaluation run (limited pages/month) at no cost.
- **Paid tier:** ~€0.02–€0.05 per page for automated transcription.

**Trade-off:** Requires uploading images to READ-COOP's cloud servers (GDPR-compliant, EU). Not self-hosted. Not API-driven in the same way as frontier VLMs.

**How to test:** Upload the 36 Phase 0 line crops to transkribus.eu, apply any available Armenian model, record CER.

---

### 3. Other Tools Evaluated and Ruled Out

| Tool | Armenian Support? | Verdict |
|------|-----------------|---------|
| PaddleOCR | No (80+ langs, Armenian not included) | Not viable without training from scratch |
| EasyOCR | No (no Armenian in official repo) | Not viable |
| ABBYY FineReader | Modern Armenian only (not Bolorgir) | Empirical test warranted but unlikely to work |
| Tesseract 5.x (generic `hye.traineddata`) | Modern Armenian print only | Dismissed theoretically here — but this row judged the WRONG model. See empirical follow-up below: calfa's historical-font `hye-calfa-n` is the right candidate and was never tested in this table. |

---

## hye-tesseract — empirical follow-up (2026-06-20)

**Local planning only — this section, like all of `docs/`, is gitignored.**

The Tesseract row above dismissed Tesseract on the basis of the *generic* `hye.traineddata`
(modern-Armenian print) — a theoretical hand-wave ("glyph shapes differ from Bolorgir") with **no
empirical test**. It judged the wrong model. The right candidate is **calfa-co/hye-tesseract**
(`hye-calfa-n.traineddata`), trained on Classical/Western/Eastern Armenian *including historical fonts
and noisy texts* — exactly the Bolorgir-adjacent regime. It is plain Tesseract-OCR + that custom
traineddata; it does no layout analysis or post-processing of its own but accepts line crops, column
crops, and full pages via PSM modes. We benchmarked it head-to-head against the fine-tuned TrOCR
pipeline on the same frozen test set, same `jiwer` CER methodology, same reports.

Setup: `brew install tesseract` (CPU, runs on the M1 Mac); `hye-calfa-n.traineddata` downloaded into the
gitignored `ml_vision/tessdata/`; `pytesseract` added to `.venv_ml`. Scripts:
`ml_vision/scripts/predict_lines_tesseract.py` (line-level, writes a predictions.json schema-identical to
`predict_lines.py` so `analyze_errors.py` scores it unchanged, under model-tag `tesseract`) and
`ml_vision/scripts/eval_tesseract_layout.py` (self-contained column/page CER). Raw OCR only — **no Phase 5
LLM post-correction** in this pass.

**PSM matters for line crops.** PSM 13 (raw line, no Tesseract layout heuristics) recognizes the crops
reliably; PSM 7 (single text line) silently returns empty on ~37/100 frozen lines → 43.3% CER. PSM 13 is
the correct mode and the number reported below.

### Line-level CER — hye-tesseract (PSM 13) vs TrOCR (beam)

TrOCR column = the current production model, the `finetune_phase4_scale_500` checkpoint (`scale_500`),
penalty-free beam-4 decoding. This is the only level at which a direct model-vs-model comparison exists.

| Test set | TrOCR scale_500 (fine-tuned) | hye-tesseract (zero-training) |
|---|---|---|
| Frozen 100 lines (held-out) | **4.4%** | **4.9%** (0 empty, arm-frac 1.00) |
| New page page_0400 (held-out, 71 lines) | **1.0%** | **4.6%** |
| page_0499 (92 lines) | ~~0.4%~~ contaminated † | 2.5% (zero-shot only) |

† **page_0499 is NOT held out for TrOCR.** All 92 of its lines are in the scale_500 training split
(`data/phase4_scaling/splits_500.json` — 79 page_0499 train ids; GT-text overlap with the eval crops is
92/92). TrOCR's 0.4% there is memorization, not generalization, so it is **not a valid head-to-head**.
hye-tesseract is zero-shot, so its 2.5% is a legitimate data point, but there is no fair TrOCR number to
compare against on this page. The only clean line-level comparisons are the **frozen set** and
**page_0400** (neither is in the training pool).

Reports written: `reports/phase4_error_analysis_frozen_tesseract.{csv,json,html}`,
`reports/phase4_newpage_page_0400_human_tesseract.*`, `reports/phase4_newpage_page_0499_human_tesseract.*`
(PSM-7 A/B under tag `tesseract_psm7`). Note: `.json` reports are gitignored repo-wide (`*.json`); the
`.csv`/`.html` are the durable artifacts.

### Layout exploration — can Tesseract segment by itself?

There is **no scale_500 TrOCR counterpart at the column or page level** — TrOCR only consumes pre-sliced
line crops, so segmentation is done upstream by our deskew + two-column + horizontal-projection pipeline
(Phase 6). The column/page numbers below therefore measure *Tesseract's own layout analysis*, and the
relevant baseline is that slicing pipeline (which feeds TrOCR its ~4.4% line-level input), not TrOCR itself.

Feeding whole column crops (PSM 4/6) and whole deskewed pages (PSM 3/1) and letting Tesseract find the
lines (and two-column reading order) is a *looser* comparison — reading-order and line-segmentation errors
fold into CER. Best CER per page (`reports/phase2_tesseract_layout.{csv,md}`):

| page | best column CER | best page CER |
|---|---|---|
| page_0400 | 37.5% (psm 4) | 37.7% (psm 3) |
| page_0499 | 7.0% (psm 6) | 12.4% (psm 3) |
| page_0251 | 30.9% (psm 4) | 39.8% (psm 3) |
| page_0550 | degenerate* | degenerate* |

*page_0550's human GT is sparse (193 chars) relative to the full page image, so Tesseract recognizes far
more text than the reference contains → CER >1000%. Not a recognition failure; an incomplete-GT artifact.
Full-page PSM 3/1 produced identical CER (PSM 1's OSD added nothing here).

Layout CER (7–40%) is far worse than the line-level number (~5%), confirming Tesseract's built-in layout
analysis is much weaker than our deskew + two-column + horizontal-projection line-slicing pipeline (Phase 6).
Keep the existing slicing pipeline; do not delegate segmentation to Tesseract.

### Verdict (against the <15% CER gate)

- **hye-tesseract is genuinely viable** for Bolorgir at the line level: 4.9% frozen / 2.5–4.6% on new
  pages, *with zero training*, CPU-only (no GPU), sub-second per line on the M1. It clears the 15% gate
  comfortably. The original table's dismissal was wrong **about the wrong model** — `hye-calfa-n` works.
- **But the fine-tuned TrOCR still wins** on the clean held-out comparisons: page_0400 1.0% vs 4.6%
  (~4.6× lower CER); frozen set near-parity (4.4% vs 4.9%). (Ignore page_0499 — contaminated for TrOCR, see
  table note.) There is **no reason to switch the production OCR backend** away from TrOCR.
- Value of hye-tesseract going forward: a strong **zero-training baseline / fallback** and a useful
  cross-check (e.g. disagreement flagging), not a replacement. Promoting it to a reusable/production backend
  and LLM post-correction of its output were explicitly out of scope for this one-off benchmark.

### fine-tuning follow-up (2026-06-20)

The zero-shot pass left one question open: *if we fine-tune `hye-calfa-n` on the exact 500-line split TrOCR
scale_500 trained on, does it match or beat TrOCR?* Tesseract is fully open (LSTM weights local, training
tools via `brew install tesseract`), so this is testable with no API. Plan:
`docs/phase_2b_hye_tesseract_finetune_plan.md`.

**Setup.** Staged the `splits_500.json` → `train` ids (the same 500 lines, same empty-skip as
`finetune_phase4.py:samples_from_splits`) as tesstrain ground-truth pairs via the new
`ml_vision/scripts/build_tesstrain_gt.py`. Contamination re-verified: page_0400 is absent from the train
split and the frozen set is a separate dir — neither leaked into the GT dir (guarded in the script). Trained
with the official **tesstrain** Makefile (`make training START_MODEL=hye-calfa-n`, MAX_ITERATIONS=4000,
LR=1e-4, PSM=13, 90/10 internal split) on CPU (M1). Output `hye-grabar.traineddata` copied to the
gitignored `ml_vision/tessdata/`. Scored with the **unchanged** harness
(`predict_lines_tesseract.py --lang hye-grabar`, then `analyze_errors.py`) under model-tag `tesseract_ft` —
same `jiwer` overall-CER metric as the zero-shot and TrOCR columns (all three re-derived here to confirm
apples-to-apples). Raw OCR, no Phase 5 LLM correction.

**Step-0 preflight (both gates clean).** (1) *Fine-tunable?* `combine_tessdata -e` extracts a 3.5 MB float
`.lstm`; `lstmtraining --continue_from` loaded it without an integer-model error ("Continuing from … /
Code range changed from 388 to 388"). The public `hye-calfa-n` **is** directly fine-tunable — no
`tessdata_best` fallback needed. (2) *Unicharset coverage?* All 87 real content characters in the 500-line
GT (every Armenian glyph + notation `՚ ։ ՝`, comma, hyphen, full stop, digits 0–9, em-dash) are already in
the model's 389-entry `lstm-unicharset`. Plain `--continue_from` on the same net — **no top-layer
replacement**. (Two crops stored a single-image-line GT with an embedded newline; tesstrain's box generator
requires one physical line, so those were space-joined — a 2/500 cosmetic deviation from TrOCR's raw
`.strip()`.)

**Line-level CER — overall beam CER, same metric across all three columns:**

| eval (clean, held-out) | zero-shot tesseract | **FT tesseract** | TrOCR scale_500 |
|---|---|---|---|
| frozen 100 lines | 4.9% | **3.5%** | 4.4% |
| page_0400 (71 lines) | 4.6% | **1.8%** | 1.0% |

Both FT reports are healthy: arm-frac 1.00, 0 empty preds, distinct preds = n (99/100 frozen, 71/71
page_0400) — not degenerate.

**Gate verdict.**
- **Primary gate (did fine-tuning help): PASSED.** FT beats zero-shot on *both* evals — frozen 3.5% < 4.9%,
  page_0400 1.8% < 4.6%. Fine-tuning on the 500-line split clearly helps (≈28% / ≈61% relative CER
  reduction).
- **Stretch gate (rival TrOCR: frozen ≤4.4% AND page_0400 ≤1.0%): PARTIALLY MET.** FT tesseract
  **beats** TrOCR on the frozen set (3.5% vs 4.4%) but **loses** on page_0400 (1.8% vs 1.0%). It closed
  most of the zero-shot gap on the new page (4.6% → 1.8%) without reaching TrOCR's 1.0%.

**Training config / runtime.** START_MODEL `hye-calfa-n`, 4000 iterations, LR 1e-4, PSM 13, 90/10 internal
split; final model = tesstrain's min-train-BCER checkpoint (train BCER 7.4% → 1.19%, monotonic — see
`reports/phase2b_tesseract_ft_cer_curve.csv`). *Caveat:* tesstrain emitted no held-out eval-CER during
training, so checkpoint selection rode train BCER alone (overfitting risk); the strong held-out frozen/0400
numbers indicate it generalized rather than overfit, so no earlier-checkpoint sweep was needed. End-to-end
~35 min wall on the M1 (CPU), dominated by one-time lstmf generation + stock-langdata download; the
4000-iteration fine-tune itself is the minutes-scale tail. No W&B (tesseract doesn't integrate); the BCER
curve is captured in the CSV above and the full log under `reports/phase2b_tesseract_ft_train.log`
(gitignored).

**Recommendation: keep TrOCR as the production backend.** TrOCR still wins on the new-page generalization
test (page_0400 1.0% vs 1.8%), which is the metric that matters for unseen pages at scale. But fine-tuning
materially strengthens hye-tesseract: it is now a **near-peer open, GPU-free, CPU-fast** model that *beats*
TrOCR on the frozen set and trails it only modestly on new pages — an even stronger **fallback / ensemble
cross-check** than the zero-shot model, and the obvious backend if the GPU/TrOCR path is ever unavailable.
Promoting it to production or LLM-correcting its output remain out of scope here.

Reports: `reports/phase4_error_analysis_frozen_tesseract_ft.{csv,html}`,
`reports/phase4_newpage_page_0400_human_tesseract_ft.{csv,html}`,
`reports/phase2b_tesseract_ft_cer_curve.csv` (`.json` is gitignored repo-wide).

**Addendum (2026-09-30, Phase 8).** The fine-tuned `hye-grabar` model (built, gate passed) was
never wired into `pipeline/registry.py`. Note also that this verdict recommended TrOCR as the
production backend, but the shipped `corpus/` was OCR'd with **zero-shot `hye-calfa-n`**, not
TrOCR. **No re-OCR will happen until line segmentation is verified** (Phases 8–9:
`docs/phase_8_line_segmentation_survey.md`, `docs/phase_9_line_segmentation_review.md`).
OCR engines (`hye-grabar`, `paddle-calfa-tiny`, `hye-open-ocr`, a Qwen-VL fine-tune) will then
be compared on verified lines from the Տօնացոյց itself. Both evals above come from a different
book, so they rank engines but do not describe the corpus.

---

## Recommended Experiment Order

Run these in order before deciding whether TrOCR fine-tuning is needed:

### Experiment A — VLM Benchmark (1–2 hours, < $2)

Write `ml_vision/notebooks/vlm_benchmark.py` that runs the Phase 0 golden set through:
1. Gemini 2.0 Flash (zero-shot)
2. Gemini 2.0 Flash (5-shot, using lines 1–5 as examples, evaluate on lines 6–36)
3. GPT-4o (zero-shot, for comparison)
4. Claude Haiku 3.5 (zero-shot)

Report CER for each. **If any model achieves CER < 30% zero-shot or < 15% with 5-shot, TrOCR fine-tuning is unnecessary for an MVP.**

### Experiment B — Transkribus Community Model (30 min, free)

Upload Phase 0 crops to Transkribus, apply any available Armenian model. Record CER.

### Experiment C — TrOCR Fine-Tuning (parallel or fallback)

Run `ml_vision/scripts/finetune_local.py` as planned in `phase_2_local_finetune.md`. This can run in parallel with Experiments A and B.

---

## Decision Tree

```
VLM benchmark CER < 15% (5-shot)?
    YES → Use Gemini 2.0 Flash as OCR engine. Skip TrOCR fine-tuning.
           Update Phase 3+ to use VLM API pipeline.
    NO  → Is Transkribus community model CER < 15%?
              YES → Evaluate Transkribus API/integration feasibility.
              NO  → Is TrOCR fine-tuned CER < 15%?
                        YES → Proceed with TrOCR on server (original plan).
                        NO  → Collect more ground truth, revisit.
```

---

## Notes

- The 15% CER threshold is a suggested target for liturgical text where word-level accuracy matters; this should be validated against the project's actual tolerance for OCR errors before translation.
- Few-shot prompting adds ~5,600 tokens/query at Gemini 2.0 Flash pricing — cost is still negligible ($0.00056/query overhead).
- Set `temperature=0` on all VLM calls for deterministic output; run each line twice and take majority vote if consistency is a concern.
- All pricing figures are estimates as of mid-2025 — verify against current provider pricing before production commitment.
