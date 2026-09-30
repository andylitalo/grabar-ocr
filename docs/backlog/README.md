# Backlog — good work that is deliberately not in the current phase

Items land here when they are worth doing but not now. Each one names what blocks it, so it
can come back when the blocker clears. The full research record behind most of these is
[`citable_corpus_roadmap.md`](citable_corpus_roadmap.md).

**The staged order all of this hangs on (set 2026-09-30):**

```
Phase 8  clean-up + line-segmentation survey → pick a baseline segmenter
Phase 9  human review / correction UI      → verified line segments, stable line ids
   ↓
cite     enumerate pages · lines · sections (every line citable)
   ↓
OCR      compare engines on verified lines, choose, re-OCR
   ↓
correct  → enumerate entries, link entry → [line ids]
   ↓
derive   armenian-lectionary cites entries (by reference + content hash)
```

| Item | What it is | Blocked by | Notes |
|---|---|---|---|
| **Line / page / section index** | Stable ids for every verified line, plus page → section (volume, taregir, month) maps as data | Phase 9 (verified lines) | First step after Phase 9. Vol II page map exists: `armenian-lectionary/docs/sources/second_volume_index.csv`. Vol I needs `corpus/STRUCTURE.md`'s table as CSV. Roadmap §5 W1. |
| **Entry enumeration + entry → line links** | The citation unit (one day's rubric), with a content hash and a link to its lines | OCR re-run on verified lines | Roadmap §5 W1, maintainer ruling. Includes the dehyphenated entry-level text. |
| **Transcription ground truth** | 300–500 hand-verified lines from *this* book, stratified by volume and typeface | Phase 9 (lines to transcribe) | Roadmap §5 W2. Gives the first real CER number for this book. |
| **`docs/ocr_approach_comparison.md`** | Fill in the `_TBD_` CER cells | Transcription ground truth | Cannot be filled honestly before then. |
| **OCR engine choice + re-OCR** | `hye-open-ocr` baseline (probably); `paddle-calfa-tiny`, `hye-grabar`, a Qwen-VL fine-tune as comparisons | Verified lines + ground truth | Roadmap §4, §5 W4/W5. |
| **`hye-grabar` registry entry** | Add the fine-tuned Tesseract model to `pipeline/registry.py` as a selectable OCR stage | OCR engine choice | Built 2026-06-20, gate passed (see `docs/phase_2_alternatives.md`). Not worth wiring in until engines are compared on verified lines. |
| **Phase 7 vision correction** | Gemini vision pass over line crops | OCR engine choice | `docs/phase_7_gemini_vision_correction.md`. Keep as an option if local engines leave a gap on display faces. |
| **Closed-vocabulary normalizer** | Deterministic fixes for tone codes, weekdays, book abbreviations (`գ3→գձ`, `Բչ→Բշ`) | Not blocked. Deprioritized. | Roadmap §5 W3. The fixes would be overwritten by the re-OCR. Its vocabulary tables are more useful later as the token-grammar check for scoring OCR engines. |
| **ERRATA backlog** | Adjudicate the "Candidate defects" list in `corpus/ERRATA.md` | Re-OCR (most items) | Frozen. Most candidates are OCR, column-order or bleed defects that re-segmentation and re-OCR will change. Hand-patching them now is work that gets thrown away. |
| **Derivation layer** | Vol I reading extractor, diff against `lectionary_data.json`, `citations` on engine rules | Entries | Built in `armenian-lectionary`. Roadmap §5 W6. |
