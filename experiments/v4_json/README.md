# v4-json: JSON answers under a response schema (2026-11-25) — not adopted

**Question.** The v4 corrector (Gemini 3.1 Pro, `dev/ocr_eval/correct.py --prompt v4`)
answers in free text, one `<number>\t<text>` row per line of the page. A row can go
missing, the model can echo both readings, or it can drop a row and renumber the rest,
which puts every later line's text under the wrong number. Each of those lines then
*falls back* to Paddle's OCR reading. Does asking for JSON under a response schema, one
required key per line number in order, remove the fallbacks without costing accuracy?

**Answer: no.** It scored no better than v4, and the fallbacks it was meant to remove
weren't misaligned answers in the first place. **v4 stays the chosen corrector**, and this
variant isn't in `dev/ocr_eval/` (maintainer, 2026-11-25).

## What was run

v4 with only its output-format rule changed (the rest of the prompt, the page text, the
line images and the checks on each answer are v4's), on the 103 ceiling pages that have
typed lines, 2026-11-25:

- **Request:** Gemini response schema: an object with keys `"1"`…`"N"`, all required,
  in order (`property_ordering`).
- **Reading the answer:** the same checks as v4. A kept `A:`/`B:` label is stripped; a
  missing line, echoed readings, or text too far from both OCR readings (the drift check)
  fall back.
- **Retry:** a page with fallback lines is asked once more, keeping the better attempt.
  The run also re-asked lines that still fell back, with 3 lines either side; that fixed
  none of the 4.

## Results

On the 163 typed ceiling lines, both with the `՚ի` rule (`ceiling score`, on the sample
strata as currently drawn; Phase 9 step 4 recomputes them). *Broke* counts lines both
engines agreed on and got right that the corrector made wrong.

| | lines | wrong on disagree | wrong on agree | error-free | 95% interval | broke |
|---|--:|--:|--:|--:|--:|--:|
| v4 | 163 | 2/60 | 4/103 | **96.3%** | 93.3–98.8% | 0 |
| v4-json | 163 | 3/60 | 4/103 | **95.7%** | 92.0–98.8% | 1 |

- **Lines where they differ** (7 of the 163, both directions):

  | line | right | typed |
  |---|---|---|
  | `p464.075` | v4-json | `… Ճաշու Սաղ. ՁԵ. Կեցո` (v4: `ԶԵ.`) |
  | `p632.057` | v4-json | `… Ոնոփրիոսի ճըգ-` (v4: `ճըդ-`) |
  | `p638.027` | v4-json | `աձ. Ըզքեզ …` (v4: `այ.`) |
  | `p519.032` | v4 | `… Ալէ. Կացցէ դըշ-` (v4-json dropped the `.`) |
  | `p489.078` | v4 | `… ահ. աձ Երգեսցուք …` (v4-json added a `.`) |
  | `p478.063` | v4 | `սանել զնան. …` (v4-json: `զնա.`; the engines agreed and were right, so v4-json **broke** the line) |
  | `p491.046` | v4 | `… Աստուած աս-` (v4-json: `Աոտուած`, the engines' shared error, which v4 fixed) |

- **Over all 8,556 lines both corrected, 219 differ (2.6%)** as scored (with the `՚ի`
  rule, normalized). That is likely Gemini's run-to-run variation; v4 hasn't been run
  twice on the same lines to measure it.
- **Cost:** 3.82M input and 0.26M output tokens for 103 pages, the same as v4's run
  (3.88M / 0.23M), about $10.
- **Fallbacks:** 4 lines (`p483.003`, `p508.011`, `p510.054`, `p520.023`), against v4's
  5 on the same 103 pages. No answer came back misaligned.

## Why the fallbacks didn't go away

The 4 lines are display headings that both OCR engines read as nonsense, for example:

| | `p508.011` |
|---|---|
| Tesseract | `Շաք.-է տատհուի 1ա-` |
| Paddle | `աթ, տն էսրոյն րիդորիԼու` |
| Gemini (both formats) | `Շաբաթ, տօն է սրբոյն Գրիգորի Լու-` |

Gemini's reconstruction is plausible but far from both readings (10 edits from the
nearer one, where the drift check allows 6.9), so the check refuses it. That is the
check doing its job: nothing can verify a rewrite that large, so these lines need a
person, whatever the answer's format. v4 fell back on the same 4 lines (it kept Paddle's
reading on each). The only misaligned answer in either run was v4's *retry* on p508
(2026-11-23), triggered by this heading line. A schema would prevent that, but no first
answer was ever misaligned.

## Reproducing it

- **Exactly as measured:** the corrector as it was then, with `--prompt v4-json`, is tag
  `exp/v4-json-2026-11-25` (commit `4ce674d`):

  ```
  git checkout exp/v4-json-2026-11-25
  uv run python -m dev.ocr_eval.correct --model gemini-3.1-pro --prompt v4-json --redo
  ```

- **On today's corrector:** `run.py` here layers the JSON request onto
  `dev/ocr_eval/correct.py` without changing it. Its prompt is checked to be identical to
  the measured run's. It leaves out the re-ask, which changed nothing.

  ```
  uv run python experiments/v4_json/run.py
  uv run python -m dev.ocr_eval.rules corr-gemini-3.1-pro-v4-json-rerun
  uv run python -m dev.ocr_eval.ceiling score
  ```

  It writes `corr-gemini-3.1-pro-v4-json-rerun` and refuses to write the measured run's
  file. `--pages 453` runs one page (a few cents) as a check.

- **The measured predictions** are committed as `corr-gemini-3.1-pro-v4-json.json` and
  `corr-gemini-3.1-pro-v4-json+rules.json` in `data/ocr_predictions/ceiling/`, so
  `ceiling score` shows the row without rerunning. Gemini's answers vary from run to run,
  so a rerun won't match them line for line.

## Related

- `docs/phase_11_ocr_comparison.md`, "Fallback lines: a re-ask, and no decision step
  (2026-11-25)": the other two options weighed, including the decision step that wasn't
  built, and the follow-up for the heading lines.
