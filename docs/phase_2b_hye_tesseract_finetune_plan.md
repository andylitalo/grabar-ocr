# Plan — fine-tune hye-tesseract, head-to-head vs scale_500 TrOCR (Phase 2b)

**Status:** ready to execute · **Created:** 2026-06-20 · **Local planning doc (gitignored).**

## Context (read first)

Phase 2's empirical follow-up (`docs/phase_2_alternatives.md`, "hye-tesseract — empirical follow-up
2026-06-20") benchmarked **zero-shot** hye-tesseract (calfa-co `hye-calfa-n.traineddata`, no training)
against the fine-tuned TrOCR pipeline. Line-level CER, raw OCR, no LLM correction:

| eval (clean, held-out) | TrOCR scale_500 | hye-tesseract zero-shot |
|---|---|---|
| frozen 100 lines | **4.4%** | 4.9% |
| page_0400 (71 lines) | **1.0%** | 4.6% |

(Ignore page_0499 from that doc — it is contaminated for TrOCR: all its lines are in the scale_500
training split. Do **not** use page_0499 as an eval page in this experiment.)

So zero-shot tesseract is already viable (clears the <15% gate) but TrOCR wins. **Open question this plan
answers:** if we fine-tune hye-tesseract on the *same training data TrOCR used* (the 500-line scale_500
split), does it match or beat TrOCR? Tesseract is fully open — the LSTM weights are local
(`ml_vision/tessdata/hye-calfa-n.traineddata`, 3.5 MB) and the training tools are installed
(`lstmtraining`, `combine_tessdata`, `lstmeval`, `unicharset_extractor`, `text2image` — all on PATH via
`brew install tesseract`). Nothing is behind an API.

## Goal & gate

Produce a fine-tuned `hye-grabar.traineddata` and score it with the **existing** harness on the **same
clean held-out evals** (frozen set + page_0400), apples-to-apples with the numbers above.

- **Primary gate (did fine-tuning help at all):** FT tesseract beats zero-shot tesseract on BOTH frozen
  (<4.9%) and page_0400 (<4.6%).
- **Stretch gate (does it rival TrOCR):** FT tesseract reaches frozen ≤4.4% AND page_0400 ≤1.0%.

Record the verdict in `docs/phase_2_alternatives.md` (a new "fine-tuning follow-up" subsection). Raw OCR
CER only — no Phase 5 LLM correction in this pass.

## Hard constraints (held-out discipline — do not violate)

- **Train ONLY on the scale_500 split**: `data/phase4_scaling/splits_500.json` → `train` ids resolve to
  `data/phase4_dataset/<page>/<line>.{png,txt}` (same loader as `ml_vision/scripts/finetune_phase4.py:
  samples_from_splits`). This is exactly the 500 lines TrOCR scale_500 trained on — that's what makes the
  comparison fair.
- **Never** put frozen-set lines (`data/frozen_test_set/`) or any page_0400 line into training. (The split
  already excludes both: frozen is a separate dir; page_0400 is not in the training pool — verify anyway.)
- Skip empty GT `.txt` (section markers), same as training/eval elsewhere.

## Step 0 — go/no-go preflight (do this BEFORE any data prep)

Two things can kill this experiment outright; check them first.

1. **Is the model fine-tunable (float, not integer)?** Quantized integer models cannot be `--continue_from`.
   Extract and test:
   ```
   mkdir -p ml_vision/tessdata_ft/scratch
   combine_tessdata -e ml_vision/tessdata/hye-calfa-n.traineddata ml_vision/tessdata_ft/scratch/hye-calfa-n.lstm
   ```
   Then a dry `lstmtraining --continue_from .../hye-calfa-n.lstm ...` (or `lstmtraining --stop_training`
   check). If it errors with an integer-model / "cannot continue from" message, the public `hye-calfa-n` is
   not directly fine-tunable. Mitigations, in order: (a) check the calfa-co/hye-tesseract repo for a
   float / `_best` variant of the model; (b) if none, STOP and report — fine-tuning from a different base
   (e.g. `tessdata_best` Armenian) loses calfa's historical-font advantage and changes the question. Make
   this a reported gate, not a silent fallback.

2. **Unicharset coverage.** Does `hye-calfa-n`'s `lstm-unicharset` contain every character in our 500-line
   GT (esp. notation: `՚ ։ ՟ · ՞ ՛ ՚ ՝` and any numerals)? Extract the model's unicharset
   (`combine_tessdata -e ... .lstm-unicharset` or `-u`) and the GT's
   (`unicharset_extractor` over the staged `.gt.txt`), diff them.
   - All GT chars present → plain fine-tuning (`--continue_from`, same net).
   - GT introduces new chars → must fine-tune with a replaced top layer
     (`lstmtraining --continue_from <lstm> --append_index ... --net_spec ...` / the tesstrain
     "plus characters" path). Note which case applies; it changes the training invocation.

## Step 1 — stage training data in tesstrain ground-truth format

Recommended engine: the official **tesstrain** Makefile (`git clone https://github.com/tesseract-ocr/tesstrain`)
— it wraps lstmf generation, unicharset build, `combine_tessdata -e`, and `lstmtraining --continue_from`
into one `make training` call. Keep the clone outside the repo or in a gitignored path.

tesstrain wants pairs `<name>.png` + `<name>.gt.txt` (one text line each) in a ground-truth dir. Write a
small prep script (`ml_vision/scripts/build_tesstrain_gt.py`) that:
- reads `data/phase4_scaling/splits_500.json`,
- for each train id `page_XXXX/line_NNN`: copy/symlink `data/phase4_dataset/page_XXXX/line_NNN.png`
  into `<tesstrain>/data/hye-grabar-ground-truth/page_XXXX__line_NNN.png` and write the sibling
  `.gt.txt` from `data/phase4_dataset/page_XXXX/line_NNN.txt` (stripped; skip if empty),
- prints the count (expect ~ up to 500 minus empty markers).

## Step 2 — fine-tune

```
cd <tesstrain>
make training \
  MODEL_NAME=hye-grabar \
  START_MODEL=hye-calfa-n \
  TESSDATA=<repo>/ml_vision/tessdata \      # must contain hye-calfa-n.traineddata
  GROUND_TRUTH_DIR=data/hye-grabar-ground-truth \
  MAX_ITERATIONS=4000 \
  LEARNING_RATE=0.0001 \
  PSM=13 \                                   # single raw line, matches the crops (zero-shot used PSM 13)
  RATIO_TRAIN=0.9
```
Notes:
- LR ~1e-4 is the usual fine-tuning rate; 500 lines is small, so watch for overfitting. Use `lstmeval` /
  the training-log CER curve on tesstrain's internal 10% eval to pick the best checkpoint (early-stop, not
  necessarily the last iteration). This internal eval is for checkpoint selection only — the *real* metric
  is Step 4 on the frozen set + page_0400.
- Output: `<tesstrain>/data/hye-grabar.traineddata`. Copy it to `ml_vision/tessdata/hye-grabar.traineddata`
  (gitignored).
- CPU-only; on the M1 a few thousand iterations over 500 lines is minutes–tens of minutes. No W&B (project
  convention is W&B for training, but tesseract doesn't integrate) — capture the CER curve from the
  lstmtraining stdout/checkpoint logs instead, and save it under `reports/`.

## Step 3 — make the scoring harness model-agnostic (small edit)

`ml_vision/scripts/predict_lines_tesseract.py` currently hardcodes `LANG = "hye-calfa-n"`. Add
`--lang` (default `hye-calfa-n`) and keep `--tessdata-dir` pointing at `ml_vision/tessdata` (both models
live there). Then the same script scores the fine-tuned model unchanged otherwise. Use model-tag
`tesseract_ft` so reports don't clobber the zero-shot `tesseract` ones.

## Step 4 — score on the clean held-out evals (reuse existing tools)

```
.venv_ml/bin/python ml_vision/scripts/predict_lines_tesseract.py --frozen --lang hye-grabar --model-tag tesseract_ft
.venv_ml/bin/python ml_vision/scripts/analyze_errors.py        --frozen --model-tag tesseract_ft

.venv_ml/bin/python ml_vision/scripts/predict_lines_tesseract.py --page page_0400_human --lang hye-grabar --model-tag tesseract_ft
.venv_ml/bin/python ml_vision/scripts/analyze_errors.py        --page page_0400_human --model-tag tesseract_ft
```
Sanity-check each report: `arm_frac` ~1.00, 0 empty preds, distinct preds ~= n (not degenerate).
Headline numbers land in `reports/phase4_error_analysis_frozen_tesseract_ft.{csv,html}` and
`reports/phase4_newpage_page_0400_human_tesseract_ft.{csv,html}` (`.json` is gitignored repo-wide).

## Step 5 — document the verdict

Add a "fine-tuning follow-up (date)" subsection to `docs/phase_2_alternatives.md` (this doc IS tracked —
gitignore exception). A 3-column table: zero-shot tesseract / FT tesseract / TrOCR scale_500, for frozen +
page_0400. State whether the primary and stretch gates passed, the training config (iterations, LR, final
checkpoint), runtime, and a recommendation (keep TrOCR / switch / use as fallback). Note any Step-0 caveat
(integer-model fallback, unicharset top-layer replacement) that qualifies the result.

## Comparison cheat-sheet (targets to beat)

| eval | zero-shot tesseract | TrOCR scale_500 | FT tesseract (this experiment) |
|---|---|---|---|
| frozen 100 | 4.9% | 4.4% | ? (gate: <4.9% primary, ≤4.4% stretch) |
| page_0400 | 4.6% | 1.0% | ? (gate: <4.6% primary, ≤1.0% stretch) |

## Files

- **New:** `ml_vision/scripts/build_tesstrain_gt.py` (stage GT pairs from splits_500.json)
- **Edit:** `ml_vision/scripts/predict_lines_tesseract.py` (add `--lang`)
- **Edit:** `docs/phase_2_alternatives.md` (FT verdict subsection)
- **New (gitignored artifacts):** `ml_vision/tessdata/hye-grabar.traineddata`, `ml_vision/tessdata_ft/`
  (scratch), tesstrain clone + `data/hye-grabar-ground-truth/`,
  `reports/*_tesseract_ft.{csv,html}`, a CER-curve log under `reports/`
- **Edit:** `.gitignore` — add `ml_vision/tessdata_ft/` (the `ml_vision/tessdata/` rule already covers the
  new `.traineddata`); ensure the tesstrain clone path is ignored if it lands inside the repo.
- **Reused unchanged:** `ml_vision/scripts/analyze_errors.py`

## Pitfalls (most likely failure modes)

1. **Integer model** → can't `--continue_from` (Step 0.1). Go/no-go.
2. **Unicharset gaps** → silent failure to learn new glyphs unless you replace the top layer (Step 0.2).
3. **Contamination** → only the scale_500 split is safe to train on; frozen + page_0400 must stay unseen.
   Re-verify no page_0400 / frozen ids leaked into the GT dir before training.
4. **PSM mismatch** → crops are single raw lines; use PSM 13 for both lstmf generation and inference
   (PSM 7 returned empty on ~37% of frozen lines in the zero-shot pass).
5. **Overfitting on 500 lines** → low LR + early-stop on eval CER; don't just take the last checkpoint.
6. **Don't commit binaries** → `hye-grabar.traineddata`, scratch, and the tesstrain clone are large/derived;
   keep them gitignored (confirm `git status` is clean of them before finishing).
