# Phase 0 Results — Micro Golden Dataset

**Date completed:** 2026-04-13
**Status:** Complete

---

## Source Material

| Field | Value |
|-------|-------|
| PDF | `data/Ժամागिরք ԱՏԵՆԻ p335.pdf` |
| Script | Bolorgir (Classical Armenian / Grabar) |
| Page | p335 (single representative page) |

---

## Pipeline Summary

| Step | Tool | Notes |
|------|------|-------|
| PDF → PNG | `data_prep/pdf_slicer.py` | 300 DPI, PyMuPDF |
| Column crop | Manual (Preview) | No layout model available; tight crop around Bolorgir column only |
| Line slicing | `data_prep/line_cropper.py` | `--padding 4`, `threshold_fraction=0.02` (defaults) |
| Transcription | Human, dictated line-by-line | Armenian Unicode; no abbreviation expansion |

---

## Output Statistics

| Metric | Value |
|--------|-------|
| Total line crops | 36 |
| Non-empty lines (for CER) | 34 |
| Empty lines (section markers) | 2 |
| Paired `.txt` files | 36 / 36 |
| Pairing check | Passed |

---

## Key Findings

- Line slicer produced clean crops on first attempt — no threshold tuning required
- 2 crops are horizontal section-marker rules (lines 28 and 29); empty `.txt` files pair them and they will be excluded from CER computation
- Column manual crop in Preview was straightforward; the page has a clear single Armenian text column
- Default `threshold_fraction=0.02` was sufficient for clean line separation

---

## Golden Dataset Location

```
data/golden/page_0001/
├── line_001.png / line_001.txt
├── ...
├── line_028.png / line_028.txt  ← empty (section marker)
├── line_029.png / line_029.txt  ← empty (section marker)
├── ...
└── line_036.png / line_036.txt
```

---

## Gate Condition

**Met.** All 36 line crops have paired `.txt` files; 34 non-empty lines exceed the ≥ 20 minimum; human spot-check confirmed accuracy.

---

## Next Step

Phase 1 — Baseline OCR: run off-the-shelf TrOCR on these crops and measure CER before any fine-tuning.
