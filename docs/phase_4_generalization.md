# Phase 4 — Generalization Test (More Labeled Data)

**Status:** Not started
**Prerequisite:** Phase 3 complete (1.0% train CER on 34-line overfit set)
**Runs on:** MacBook Pro M1 Pro — labeling is manual; training and eval are local

---

## Goal

Find out whether the fine-tuned TrOCR model generalizes to *unseen* pages, not just the 34 lines it memorized. To do this we need more labeled data so we can split into a proper train set and a held-out eval set.

The Phase 3 result (1.0% CER) is encouraging but tells us nothing about generalization — the model saw every training line hundreds of times. This phase answers: **does the model actually read Bolorgir, or did it just memorize 34 lines?**

---

## Target Dataset Size

| Set | Pages | Approx. lines |
|-----|-------|---------------|
| Train (including Phase 0 page) | 5–8 pages | ~150–250 lines |
| Held-out eval | 2–3 pages | ~60–100 lines |
| **Total new labeling needed** | **~6–10 new pages** | **~180–320 lines** |

Pick pages from the same source PDF (`Ժամागिरք ԱՏԵՆԻ p335.pdf`) or another Bolorgir book of comparable quality. Variety in page content is more useful than variety in script style at this stage.

---

## How to Label a New Page

This is the same process used in Phase 0. Here it is step by step:

### Step 1 — Pick a page

Choose a page that:
- Has clean, legible Bolorgir script (no water damage, bleed-through, or torn edges)
- Contains ~25–40 lines of text
- Includes a mix of long and short lines, and ideally a few `՚ի` elision marks

Avoid: pages that are mostly decorative headers, full-page illustrations, or Latin/transliteration columns.

### Step 2 — Convert the PDF page to a PNG

From the repo root with the venv active:

```bash
source .venv/bin/activate
python data_prep/pdf_slicer.py \
  --input /path/to/your/book.pdf \
  --output /tmp/grabar_pages/ \
  --dpi 300
```

This produces one PNG per page (e.g. `page_0335.png`). Pick the PNG for your chosen page.

### Step 3 — Crop the Armenian column

No layout model exists yet, so do this manually in Preview (Mac):

1. Open the page PNG in Preview
2. Use **Tools → Rectangular Selection** to draw a tight box around the Armenian text column only — exclude page numbers, Latin transliteration columns, and margins
3. **Tools → Crop** (⌘K)
4. **File → Export** → save as PNG to e.g. `/tmp/grabar_columns/page_NNNN_column.png`

The crop should include the full width of the Armenian column with a few pixels of margin on each side, and span from the first line to the last.

### Step 4 — Slice the column into line crops

```bash
python data_prep/line_cropper.py \
  --input /tmp/grabar_columns/page_NNNN_column.png \
  --output /tmp/grabar_lines/page_NNNN/ \
  --padding 4
```

This produces `line_001.png`, `line_002.png`, etc.

**Inspect the output** before transcribing — open the directory in Finder and flip through the crops:
- Each crop should contain exactly one line
- No line should be clipped on left or right
- Ascenders (tall letters) and descenders should not be cut off

If lines are merged or split, re-run with `--padding 2` (tighter) or `--padding 6` (looser) and check again. In Phase 0 the defaults worked on the first attempt — they likely will here too.

### Step 5 — Transcribe each line

For each `line_NNN.png`, create a `line_NNN.txt` in the **same directory** containing the exact Grabar text of that line.

**Transcription rules (same as Phase 0):**
- Type Armenian Unicode characters exactly as printed — do not guess or correct
- Preserve `՚ի` elision marks as `՚` (U+055A) — do not expand
- Do not expand *pativ* abbreviations — transcribe what is literally on the page
- Do not correct spelling or punctuation
- If a line is a horizontal rule, folio number, or section marker with no readable text, create the `.txt` file and **leave it empty** — it will be excluded from CER computation

**Keyboard setup (Mac):**
- System Settings → Keyboard → Input Sources → add "Armenian"
- Switch with the input menu in the menu bar, or assign a keyboard shortcut
- Alternative: copy-paste from an Armenian Unicode chart for characters you can't find

**Workflow tip:** Open the line image and a text editor side by side. Work line by line — it goes faster than it looks. Phase 0's 34 lines took about 1–2 hours total including setup.

### Step 6 — Move crops into the golden dataset

Once transcription is complete for a page, move the crops into:

```
data/golden/page_NNNN/
├── line_001.png
├── line_001.txt
├── line_002.png
├── line_002.txt
└── ...
```

Run the pairing check to make sure every PNG has a TXT:

```bash
for f in data/golden/page_NNNN/*.png; do
  [ -f "${f%.png}.txt" ] || echo "MISSING: $f"
done
```

Repeat Steps 1–6 for each new page.

---

## Train / Eval Split

Once all pages are labeled, designate pages for train vs. eval **before running any training** — do not look at model output on eval pages first.

Suggested split (adjust based on final page count):

| Role | Pages |
|------|-------|
| Train | `page_0001` (Phase 0) + 5–7 new pages |
| Held-out eval | 2–3 new pages not used in training |

Keep the eval pages physically separate — do not inspect model predictions on them until after training.

---

## Training Run

Re-run `ml_vision/scripts/finetune_local.py` with the expanded train set. Before running, update `GOLDEN_DIR` in the script (or refactor to accept multiple page directories). Key parameters to consider adjusting:

- `num_train_epochs`: with ~200 lines, 30–50 epochs is reasonable; watch for eval CER plateau
- `per_device_train_batch_size`: keep at 4 for M1 memory headroom
- `eval_strategy`: evaluate on the held-out set, not the train set

---

## Gate Condition

**Phase 4 is complete when:** Held-out eval CER is measured on pages the model has never seen.

---

## Decision After Gate

| Held-out CER | Next step |
|---|---|
| < 15% | Generalization confirmed. Move to server setup (Phase 5) and full-book inference. |
| 15%–40% | Partial generalization. Collect more data (target 500–1000 lines) before server work. |
| > 40% | Not generalizing. Investigate: is the eval set from a different book/script style? Consider data augmentation or a different base model. |

---

## Notes / Findings

### Honest generalization (2026-05-29)
- Train page_0335 + page_0543 (119 lines), eval page_0559 (89 lines, held out).
- **17.6% held-out CER** — PARTIAL (15%–40% band). Generalizes (down from 93.4%
  baseline) but above the 15% gate. Bottleneck is data volume, not recipe.
- Full write-up: `reports/phase_4_results.md`.

### CER-vs-data scaling experiment (2026-05-30)
Merged all 9 labeled pages → **613 non-empty lines**. Held out a **fixed 100-line**
test set (`data/frozen_test_set/`, seed 42); trained nested subsets (50 ⊂ 150 ⊂ 500)
on the remaining 513-line pool; eval'd every run against the same frozen 100 lines.
This is a **line-level random split** (train/test lines may share a page), so it is
*more optimistic* than the page-holdout 17.6% — it answers "how much does more data
help?", not "does it generalize across pages?".

| n_train | held-out CER |
|--------:|:------------:|
| 50  | 90.6% |
| 150 | 30.0% |
| 500 | **2.5%** |

- Data is decisively the lever: 3 orders of CER improvement from quantity alone,
  recipe held fixed. Curve still steep over 150→500.
- **500 ≈ data ceiling** (~97% of the 513-line pool) — can't extend without more pages.
- Tooling: `data_prep/build_scaling_splits.py`, `ml_vision/scripts/finetune_phase4.py
  --splits <path>` (supports `--resume`), `ml_vision/scripts/plot_scaling.py`. ML env
  is the `[ml]` extra in `pyproject.toml` → `.venv_ml`.
- Full write-up + plot: `reports/phase_4_results.md`, `reports/phase4_scaling.png`.

### Next step
Label beyond the current 9 pages, then re-measure with a **page-held-out** set at
~500+ lines to separate cross-page-real CER from within-page-optimistic CER.
