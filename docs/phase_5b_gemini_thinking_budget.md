# Phase 5b — Gemini thinking-budget × model sweep (speed vs quality)

## Motivation
The pipeline calls `gemini-3.1-pro-preview` for **correction** (minimal-edit) and
**translation** with **no thinking budget set**. Because 3.1-pro is a reasoning
model, it defaults to dynamic/high thinking. Measured on page_0474 (92 lines):

| Config (translation call) | Wall | out tok | **thinking tok** |
|---|---|---|---|
| current (no thinking cfg) | **92.0s** | 638 | **15,358** |
| `thinking_budget=512` | **10.7s** | 1,315 | (capped) |
| `thinking_budget=0` | rejected — 3.1-pro requires thinking mode | | |

So ~92% of per-page latency (~2.8 min/page) is **invisible reasoning tokens**, not
compute. The Gemini console feels fast because it uses a small default budget *and*
streams. A budget cap made the identical call **~8.6× faster**. Before resuming the
full-book run we must confirm a capped/cheaper config **preserves quality**.

This is a gate-style investigation: do not change production model config until the
gate below is passed and findings recorded here.

## Variables
- **Model:** `gemini-3.1-pro-preview` (current) vs `gemini-3.5-flash` (cheaper/faster).
- **Thinking budget:** `gemini-3.1-pro` — dynamic (current, ≈ -1), 2048, 512, 128
  (and the minimum it accepts; budget=0 is rejected). `gemini-3.5-flash` — 0
  (non-thinking, if accepted), 512, dynamic.
- **Stage:** correction (minimal-edit) and translation, swept independently — the two
  stages may land on different optimal configs.

## Data
- **Correction CER** (has ground truth): held-out human pages **page_0400 (71 lines),
  page_0451 (68), page_0499 (93)**. Baseline OCR = **tesseract** (the production engine
  for the book run). Score corrected text vs human `.txt` GT with `jiwer` (corpus CER
  over text lines), exactly like `analyze_errors.py`.
- **Translation quality** (no GT): **page_0400, page_0474**. Judge by (a) completeness
  — line/item count preserved, nothing dropped/invented; (b) LLM-as-judge faithfulness
  vs the **source Grabar** AND vs the current uncapped-pro output as reference.

## Metrics (per cell)
latency (s), prompt/output/**thinking** tokens, cost ($); correction also CER and
Δ-vs-tesseract-baseline; translation also completeness + judge score.

## Gate / decision rule
- **Correction:** pick the cheapest+fastest config whose **mean CER across the 3 GT
  pages is within +0.3 abs CER** of the current production config (tesseract +
  3.1-pro dynamic-thinking), AND still below the raw tesseract-baseline CER (correction
  must help, not hurt). The Phase-5 reference: page_0400 1.0%→0.27% on TrOCR baseline.
- **Translation:** pick the cheapest+fastest config with **zero content drops** and
  judge faithfulness **≥ the uncapped-pro reference** (within tolerance).

## Implementation
- Self-contained sweep script in the worktree (`experiments/gemini_budget_sweep.py`),
  monkeypatching `llm_correct.call_gemini` with a **thinking_budget-aware** variant so
  it exercises the exact production correction prompt + parse + the translation path —
  production code stays untouched until the gate is decided.
- Results → `reports/phase5b_budget_sweep.{csv,md}`; a side-by-side translation diff
  for human spot-check.
- **Cost guard:** correction ≈ 3 pages × 2 models × ~4 budgets ≈ 24 calls; translation
  ≈ 2 × 2 × ~4 ≈ 16 calls; + judge ≈ 16. ~56 calls total, bounded (~$0.5–1.5).

## Deliverable / next step
A recommended **production config per stage** (model + thinking_budget). Wire it into
`call_gemini` / the registry on `feat/book-run`, then resume the book run with the cap
**+** the approved page concurrency. Pricing (`PRICE_PER_MTOK`) for gemini is currently
an ESTIMATE — confirm 3.1-pro and 3.5-flash rates while here so the cost column is real.

## Findings (sweep run 2026-06-26 — `reports/phase5b_budget_sweep.csv`)

### Correction (CER vs human GT, tesseract baseline; pages 0400/0451/0499)
Baseline tesseract CER: 0400 4.56% · 0451 1.93% · 0499 2.51% (mean 3.00%).

| model / budget | 0400 | 0451 | 0499 | mean | made_worse | latency |
|---|---|---|---|---|---|---|
| **3.1-pro dynamic** | 4.36 | 1.80 | 1.86 | **2.67** | 0 | 40–100s |
| 3.1-pro 2048 | 4.49 | 1.80 | 1.86 | 2.72 | 0 | 14–23s |
| **3.1-pro 512** | 4.49 | 1.80 | 2.03 | **2.77** | 0 | **8–13s** |
| 3.1-pro 128 | 4.49 | 1.80 | 2.13 | 2.81 | 0 | 9–16s |
| 3.5-flash dynamic | 4.49 | 1.73 | 1.96 | 2.73 | 0 | 25–60s |
| 3.5-flash 512 | 3.27 | 1.00 | **3.79** | 2.69 | **7** | 1–2s |
| 3.5-flash 0 | 1.50 | 1.00 | **4.54** | 2.35 | **4** | 1–2s |

**Flash with a capped/zero budget over-corrects the notation-dense page (0499): CER
rises ABOVE baseline (2.51→3.79/4.54) and 4–7 lines are made worse** — the exact
failure mode the Phase-5 notes warned about. Flash is therefore **unsafe for
correction**. Among pro budgets, **512 matches dynamic within +0.10 abs CER, never
makes a line worse, and runs ~5–8× faster (8–13s vs 40–100s)**. → **Correction =
gemini-3.1-pro, thinking_budget=512.**

### Translation (no GT — completeness + faithfulness read; pages 0400/0474)
out_lines vs src_lines is noisy (translation legitimately reflows), so candidates
were read directly. Aggressive **pro** caps collapse content (0474: 512→14, 128→14
lines — truncated). Safe, complete candidates: pro 2048, pro dynamic, **flash 512**,
flash 0.

Reading 0400 + 0474: **flash@512 is complete and faithful** — same items in order,
ends at the same final line as pro-dynamic, and on 0400 it *reassembles* the OCR's
broken half-lines into whole Psalm verses (445 vs 380 words) and adds allowed
transliterations. **9.6s vs pro-dynamic 69s** (~7× faster), comparable quality.
Translation is generative, so the correction over-edit failure mode does not apply.
→ **Translation = gemini-3.5-flash, thinking_budget=512.**

**Cost correction:** confirmed pricing (2026-06) is 3.1-pro $2/$12, **3.5-flash
$1.50/$9.00** per 1M (ai.google.dev/gemini-api/docs/pricing) — flash is only ~25%
cheaper per token, not the 5× my first estimate assumed. Accounting for flash's
larger output, translation cost is ~**flat** (~$0.02/page either model). **The win
is speed, not cost.**

### Decision
| stage | model | thinking_budget | was | now |
|---|---|---|---|---|
| correction | **gemini-3.1-pro** | **512** | ~40–100s | ~8–13s |
| translation | **gemini-3.5-flash** | **512** | ~69–92s | ~9s |

Per digitized page ≈ 13s OCR + ~10s correct + ~9s translate ≈ **~32s** (was ~169s) —
~5× faster *before* concurrency; with page concurrency the full book is < ~15 min.
Cost ≈ $0.004 (correct, pro@512) + ~$0.02 (translate, flash@512) ≈ **~$0.025/page** —
about the SAME as before (the speedup does not lower cost). `PRICE_PER_MTOK` updated
with confirmed rates.

### Wiring (production change on `feat/book-run`)
1. `llm_correct`: register `gemini-3.5-flash` in `MODELS`/`PRICE_PER_MTOK`; add a
   per-api-model `GEMINI_THINKING_BUDGET` lookup that `call_gemini` applies (thread-safe,
   read-only — correction=pro and translation=flash never share a budget).
2. `registry.TRANSLATORS`: add a `gemini-flash` entry (cli_model gemini-3.5-flash).
3. Run the book with `--translate gemini-flash`; correction default already = 3.1-pro.
4. Then add page concurrency and resume.
