# Grabar OCR approach comparison — results

Where the head-to-head between Grabar transcription approaches is recorded, so the corpus can
be re-OCR'd with the best one. Populated by the Phase 7 build
(`docs/phase_7_gemini_vision_correction.md`) and any TrOCR/Tesseract re-runs. **This file is
the deliverable the user asked for: the comparison results live here, not inline in the plan.**

> **Scope:** this doc compares OCR **transcription** engines. The orthogonal **line-segmentation**
> axis (shipping projection slicer vs. kraken neural baselines) is compared separately in
> `docs/kraken_line_segmentation.md`.

## Approaches under comparison

| id | Approach | Channel / cost | Status |
|----|----------|----------------|--------|
| `tess` | Baseline Tesseract (**current corpus**) | local, free | in use |
| `tess+llm` | Tesseract + `gemini-3.1-pro` text-only correction (minimal-edit) | batch API, cheap | in use (correction) |
| `tess_ft` | Fine-tuned Tesseract | local, free | predictions for 1 page |
| `trocr500` | Fine-tuned TrOCR (`scale_500`) | local GPU, ~free | 7 pages; Phase 3/4 |
| `trocr500+llm` | TrOCR + LLM text-correction | local + batch API | variants exist |
| `g35flash_vlm` | **Gemini-3.5-flash VISION correction** (Phase 7) | batch API, ~$3–28 one-time | POC ✅, not built |
| `claude_vlm` | Claude vision (interactive) — **gold reference only** | interactive API, expensive | p453 done (reference) |

## Metrics
- **CER** (jiwer, via `pipeline/scoring.py`) on labeled/gold lines — overall, and split
  **display/heading vs. body Bolorgir** (the failure clusters differ).
- **Noise handling:** precision/recall of "is non-character" vs. human `nonchar_truth.json`;
  hard bar = **0 real-text lines dropped**.
- **Cost:** $ per line and extrapolated to the 13,873-line corpus.
- **Speed:** wall-clock per page; whole-corpus estimate.
- **Failure notes:** qualitative (e.g. punctuation drift, hallucination).

## Evaluation set
Use the existing ground truth so results are comparable to prior phases:
`data/golden/`, `data/frozen_test_set/`, the Phase 4 held-out page(s) (e.g. `page_0559_human`),
and `reports/nonchar_truth.json` for noise. Add ≥1 **display-font page** (e.g. **p453**, whose
hand-verified reference is in `corpus/book.grabar.corrected.md`) since that is where approaches
diverge most and none of the older phases measured it.

## Results

### Overall CER (lower is better)
| approach | overall CER | display CER | body CER | eval set | date |
|----------|-------------|-------------|----------|----------|------|
| `tess` | _TBD_ | _TBD_ | _TBD_ | | |
| `tess+llm` | _TBD_ | _TBD_ | _TBD_ | | |
| `trocr500` | ~0.176 (held-out body, Phase 4) | _TBD_ | 0.176 | page_0559_human | 2026-05-29 |
| `g35flash_vlm` | _TBD_ | _TBD_ | _TBD_ | | |

### Noise handling (non-character)
| approach | precision | recall | real-text dropped | notes |
|----------|-----------|--------|-------------------|-------|
| image `line_filter` (current) | _TBD_ | low | 0 | fires ~once corpus-wide (misses text-garble) |
| `g35flash_vlm` (`[NON-CHARACTER]`) | _TBD_ | _TBD_ | _TBD_ (target 0) | flagged p453 dividers correctly in POC |

### Cost & speed
| approach | $/line | $ / full corpus | notes |
|----------|--------|-----------------|-------|
| `tess`, `tess_ft`, `trocr500` | 0 | ~0 | local compute |
| `g35flash_vlm` per-line | ~$0.002 | **~$28** | POC measured (p453, p519) |
| `g35flash_vlm` column-batched | _TBD_ | **~$3–5 est.** | ~10× fewer image tokens |
| `claude_vlm` (reference) | high | not viable | in-chat; reference only |

## Known data points (from prior work, for context)
- Off-the-shelf TrOCR baseline CER **93.4%** (`docs/phase_1_baseline_ocr.md`).
- TrOCR fine-tune: **17.6% held-out CER**, verdict PARTIAL; bottleneck is **labeled-data
  quantity (~500–1000 lines)**, not recipe (`reports/phase_4_results.md`).
- Gemini-flash vision POC (Phase 7): recovers display + body text, flags noise; **~$28
  per-line / ~$3–5 column-batched**; caveat = punctuation/spacing normalization needed.

## Decision log
- **2026-07:** Chose to prototype `g35flash_vlm` first (cheapest quality lever; same model as
  the good English translation). If it fails the gate or costs too much, fall back to labeling
  more data → re-fine-tune `trocr500` (Phase 3/4). See `corpus/ERRATA.md` E2.
- _next: fill the tables above from the Phase 7 build, then pick the corpus OCR._
