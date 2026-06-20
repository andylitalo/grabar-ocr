# Phase 0 — Micro Golden Dataset

**Status:** Complete
**Estimated manual effort:** 1–2 hours
**Prerequisite:** A sample PDF containing at least 1 page of Bolorgir-script Classical Armenian text

---

## Goal
Produce the smallest possible ground-truth dataset: one fully transcribed page of Grabar text. This dataset serves two purposes:
1. **Phase 1 input** — gives us line crops + reference text to measure baseline CER
2. **Phase 3 seed** — the training split will be used for a first fine-tuning run to prove the concept before committing to a larger labeling effort

The guiding principle is *prove assumptions cheaply*. If Phase 1 shows the off-the-shelf model already performs well (< 5% CER), we may not need a large golden dataset at all. Transcribing 1 page keeps the sunk cost low.

---

## Automated Steps (run these first)

These steps use code that is already written in `data_prep/`.

### 1. Pick a page
Choose 1 page from your PDF that:
- Has clean, legible Bolorgir script (no water damage, minimal bleed-through)
- Contains a representative density of text (~25–40 lines)
- Includes at least a few *pativ* abbreviations (the abbreviated superscript forms) if present — these are exactly what the off-the-shelf model will struggle with

### 2. Convert the PDF to an image
```bash
python data_prep/pdf_slicer.py \
  --input /path/to/your/book.pdf \
  --output /tmp/grabar_pages/ \
  --dpi 300
```
This produces one PNG per page. Pick the PNG for your chosen page.

### 3. Detect and crop the Armenian column
> **Note:** `layout_detector.py` requires a trained YOLOv8 column-detection model (`--model` flag). For Phase 0, if that model does not yet exist, skip this step and manually crop the Armenian column in an image editor (Preview on Mac works fine). Save the crop as `page_0001_column.png`.

```bash
# If you have a layout model:
python data_prep/layout_detector.py \
  --image /tmp/grabar_pages/page_0001.png \
  --model /path/to/layout_yolov8.pt \
  --output /tmp/grabar_columns/

# If you do NOT have a layout model yet:
# Manually crop the Armenian column in Preview → Export as PNG
# Save to: /tmp/grabar_columns/page_0001_column.png
```

### 4. Slice the column into line crops
```bash
python data_prep/line_cropper.py \
  --input /tmp/grabar_columns/page_0001_column.png \
  --output /tmp/grabar_lines/page_0001/
```
This will produce files named `line_001.png`, `line_002.png`, etc.

### 5. Inspect the crops
Open the output directory and visually check:
- Each crop contains exactly one line of text (not zero, not two)
- Crops are not clipped on the left/right
- Crop height includes ascenders and descenders

If lines are merged or split, tune the `--padding` argument or manually adjust the `threshold_fraction` in `line_cropper.py`.

---

## Manual Step — Transcription

For each `line_NNN.png`, create a corresponding `line_NNN.txt` file in the **same directory** containing the exact Grabar text of that line.

### Transcription rules
- Type the Armenian Unicode characters exactly as they appear (use a Unicode Armenian keyboard layout)
- Preserve *pativ* abbreviations as they appear on the page — do **not** expand them; we want the model to learn expansion itself
- Do not correct spelling or punctuation — transcribe what is literally printed
- If a line is a page header, folio number, or decorative element with no readable text, create the `.txt` file but leave it empty (it will be excluded from CER computation)

### Recommended tools
- **Mac keyboard**: System Preferences → Keyboard → Input Sources → add "Armenian"
- **Alternative**: Copy-paste from an Armenian Unicode chart if you need specific characters

### Output structure
```
data/golden/
└── page_0001/
    ├── line_001.png
    ├── line_001.txt   ← exact Grabar text of that line
    ├── line_002.png
    ├── line_002.txt
    └── ...
```

> The `data/` directory is in `.gitignore`. Raw images and ground truth text stay local or go to GCS — never committed to git.

---

## Validation Checklist

Before marking this phase complete, verify:

- [x] All `.png` files in `data/golden/page_0001/` have a paired `.txt` file
- [x] No `.txt` file is missing (run: `for f in data/golden/page_0001/*.png; do [ -f "${f%.png}.txt" ] || echo "MISSING: $f"; done`)
- [x] Spot-check 5 random line pairs — the `.txt` matches what you see in the `.png`
- [x] At least 20 non-empty lines (fewer means the column crop or line slicer needs adjustment)

---

## Gate Condition

**Phase 0 is complete when:** every line crop for 1 page has a verified `.txt` transcription, and a human spot-check confirms accuracy.

Record the total line count here once done: **Line count: 36 (34 non-empty, 2 empty section markers)**

---

## Notes / Findings

- Source: `Ժամագիրք ԱՏԵՆԻ p335.pdf` — single page, Bolorgir script
- PDF → PNG at 300 DPI using `data_prep/pdf_slicer.py`
- No layout model available; Armenian column cropped manually in Preview
- Line slicer (`data_prep/line_cropper.py`) with default `threshold_fraction=0.02` and `--padding 4` produced clean crops on first attempt — no tuning needed
- 2 crops are horizontal section-marker lines (lines 28, 29); paired `.txt` files are empty and will be excluded from CER computation
- Transcription performed by human, dictated line-by-line
