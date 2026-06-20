# Phase 2 — VLM & Transkribus Benchmark

**Status:** Complete
**Prerequisite:** Phase 1 complete (baseline CER = 93.4% with trocr-base-printed)
**Runs on:** MacBook Pro M1 Pro — API calls only, no GPU required
**Background:** `docs/phase_2_alternatives.md` contains the full alternatives analysis that motivated this phase

---

## Goal

Before committing to TrOCR fine-tuning, determine whether a frontier VLM or Transkribus community model already achieves acceptable CER on the Phase 0 golden data — with zero training effort. Two experiments:

- **Experiment A:** Benchmark all major frontier VLMs (Google, OpenAI, Anthropic) zero-shot and 5-shot
- **Experiment B:** Test any available Armenian community model on Transkribus (manual, free)

If any approach reaches CER < 15%, TrOCR fine-tuning (Phase 3) becomes optional.

---

## Experiment A — VLM Benchmark

### Models (verified April 2026)

| Provider | Flagship | Fast tier |
|----------|---------|-----------|
| Google | `gemini-2.5-pro` | `gemini-3.1-flash` (if available; else skip) |
| OpenAI | `gpt-5.4` | `gpt-5.4-mini` |
| Anthropic | `claude-sonnet-4-6` | `claude-haiku-4-5` |

> Note: Gemini 2.0 Flash is deprecated and shuts down June 1, 2026 — do not use.

### Prompt

```
You are an expert paleographer specializing in Classical Armenian (Grabar) manuscripts.
The image shows a single line of text written in Bolorgir script — a printed calligraphic
style used in Armenian liturgical books from the 17th–19th centuries.

Transcribe the text exactly as written, using Armenian Unicode characters (U+0531–U+058F).
Output ONLY the Armenian text. Do not transliterate. Do not expand abbreviations.
Use ՚ (U+055A) for elision marks if visible. Use ։ (U+0589) for full stops.
```

### Variants

- **Zero-shot:** Prompt only + line crop image
- **5-shot:** Prepend lines 1–5 as image+transcription examples; evaluate on lines 6–36

### Script

`ml_vision/notebooks/vlm_benchmark.py` — to be created. Reads `.env` for API keys:
- `GEMINI_API_KEY` → `google-generativeai` SDK
- `OPENAI_API_KEY` → `openai` SDK
- `ANTHROPIC_API_KEY` → `anthropic` SDK

Dependencies to install: `google-generativeai`, `openai`, `anthropic`, `python-dotenv`
Already in venv: `jiwer`, `Pillow`

### Output

- Per-line predictions printed: `line_NNN.png: '<prediction>' | GT: '<ground_truth>'`
- Section markers reported separately (same hallucination check as Phase 1)
- CER per model/variant reported at end
- All results saved to `reports/phase_2_vlm_results.md`

---

## Experiment B — Transkribus Community Model

Manual steps (no script needed):

1. Create a free account at [transkribus.eu](https://transkribus.eu)
2. Create a new document and upload all 36 line crops from `data/golden/page_0001/`
3. In the **HTR** tab, browse the public model library — search for "Armenian", "historical", or "Bolorgir"
4. Apply any promising model; download the transcription output
5. Compute CER manually against the `.txt` ground truth:
   ```bash
   # after downloading Transkribus output as .txt files to /tmp/transkribus_output/
   python -c "
   from jiwer import cer
   from pathlib import Path
   refs, hyps = [], []
   for p in sorted(Path('data/golden/page_0001').glob('*.txt')):
       gt = p.read_text().strip()
       if not gt: continue
       hyp_path = Path('/tmp/transkribus_output') / p.name
       hyp = hyp_path.read_text().strip() if hyp_path.exists() else ''
       refs.append(gt); hyps.append(hyp)
   print(f'Transkribus CER: {cer(refs, hyps)*100:.1f}%')
   "
   ```
6. Record model name and CER in results table below

---

## Results

*(Fill in after running)*

### Experiment A — VLM CER

| Model | Zero-shot CER | 5-shot CER | Notes |
|-------|--------------|------------|-------|
| `gemini-2.5-pro` | 100.0% | 100.0% | Refused/empty output — no Armenian Unicode produced |
| `gemini-3.1-flash` | 100.0% | 100.0% | Refused/empty output |
| `gpt-5.4` | 100.0% | 100.0% | Refused/empty output |
| `gpt-5.4-mini` | 100.0% | 100.0% | Refused/empty output |
| `claude-sonnet-4-6` | 90.2% | 152.3% | Best zero-shot; 5-shot degraded (over-insertion) |
| `claude-haiku-4-5` | 260.7% | 121.4% | Worst zero-shot; 5-shot improved but still far above threshold |

### Experiment B — Transkribus

| Model name | CER | Notes |
|-----------|-----|-------|
| N/A | N/A | No Armenian (Bolorgir or otherwise) models found in public library as of 2026-04-25 |

---

## Gate Condition

**Phase 2 is complete when:** CER is recorded for all VLM variants and at least one Transkribus model (or a note that no Armenian model exists in the library).

---

## Decision After Gate

| Best CER achieved | Next step |
|---|---|
| < 15% | Use that model as OCR engine. Phase 3 (TrOCR fine-tuning) is optional/deferred. Update architecture. |
| 15%–40% | Promising but not production-ready. Consider more labeled data + few-shot tuning, or proceed to Phase 3 to compare. |
| > 40% | VLMs insufficient for this script. Proceed to Phase 3 (TrOCR fine-tuning). |

---

## Notes / Findings

- **Experiment A (VLM):** Best result was `claude-sonnet-4-6` at 90.2% zero-shot CER — still well above the 15% threshold. GPT-5.4 and both Gemini models produced 100% CER (refused to output Armenian Unicode or produced empty strings). 5-shot made things worse for all models (insertion hallucinations). No VLM is viable as a drop-in OCR engine for Bolorgir script.
- **Experiment B (Transkribus):** No Armenian (Bolorgir or otherwise) community models exist in the Transkribus public library as of 2026-04-25. Confirmed by manual search.
- **Decision tree outcome:** All paths > 40% CER → **Proceed to Phase 3 (TrOCR fine-tuning).**
- Full per-line VLM results in `reports/phase_2_vlm_results.md`.
