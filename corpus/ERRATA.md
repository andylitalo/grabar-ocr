# Տօնացոյց (Tōnatsooyts) — Digitization & Translation Errata

A registry of defects **introduced by digitization** — i.e. places where this corpus's
Grabar transcription or English translation is **wrong relative to what the printed page
actually says**. Causes: OCR error/garble, LLM mistranslation, cropping/column/margin
bleed, dropped lines, or untranslated Armenian.

> **This is NOT [`TYPOS.md`](TYPOS.md).** `TYPOS.md` records errors in the *printed source*
> (which the corpus faithfully reproduces). `ERRATA.md` records errors *we* introduced,
> where the corpus diverges from the source. If the page prints it correctly but our text is
> wrong → here. If the page itself is wrong → `TYPOS.md`.

**Corrections are non-destructive.** The generated `book.english.md` / `book.grabar.md` and
`pages/*.{md,lines.json}` are **never edited** (a `pipeline.promote` re-run regenerates them).
Approved fixes are applied to the sparse overlays
[`book.english.corrected.md`](book.english.corrected.md) /
[`book.grabar.corrected.md`](book.grabar.corrected.md), and each is logged here.

## Workflow (Phase B, user-in-the-loop)
Reviewed in batches by section/page range. For each candidate defect:
1. Adjudicate against the source: read the page's `pages/page_NNNN.lines.json` (`ocr_raw`,
   `grabar`) and, when needed, the line image it points at
   (`data/lines/page_NNNN_*/<region>/line_NNN.png`).
2. Classify: **translation** (English wrong, Grabar ok) · **transcription** (Grabar/OCR
   wrong) · **bleed** (margin/other-column contamination to delete) · **structure**
   (misordered columns / dropped lines) · **coverage** (missing pages).
3. Surface to the maintainer for a decision; record the row below.
4. Apply the approved text to the relevant overlay; normalize terms per
   [`GLOSSARY.md`](GLOSSARY.md).
5. Defects rooted upstream (bad crop, column swap, missing page) that can't be hand-patched
   go under **Reprocessing candidates** for an optional pipeline re-run.

## Entry format
```
### E<n>. <short title> — page NNNN [class]
- Location: corpus/pages/page_NNNN.md:<line> (or book.english.md ## page_NNNN)
- Prints (source): <what the page/grabar actually says>
- Corpus has: <the wrong English/Grabar currently in the corpus>
- Correction: <approved fix, applied to which overlay>
- Evidence: <line image / lines.json line_id / external cross-check>
```

---

## Confirmed defects

### E1. Vol II p.557 year-letter mislabeled Գ, is Ա — page 0557 [transcription + translation]
- **Status: CONFIRMED** by maintainer (2026-07) — "p.557 is an Ա."
- Location: `book.english.md ## page_0557` header — "THE YEARLY LETTER: [Gg - Գ]".
- Prints (source): taregir **Ա**. `second_volume_index.csv` gives `Ա, 03-22, 557, 4`; the
  section's cycle line reads "…ՀՌՈՎՄԱՅԵՑԻՒՈՑ 4" (=4 ✓) and its March row is "March 22 … Easter" (✓).
- Root cause (two layers):
  - *Transcription:* the grabar header is garbled — `ԳԳԳԻՐ ՏԱՐԻՒՈՅՆ` is a mangled
    «ԳԻՐ ՏԱՐՒՈՅՆ» ("Letter of the year"); the true letter line is the garbled `ԱԸԱ` (contains Ա).
  - *Translation:* Gemini took the stray `Գ` out of the mangled word «ԳԻՐ» and reported it as
    the year-letter value → "[Gg - Գ]".
- Correction: header year-letter = **Ա**. To be applied to `book.english.corrected.md`
  (label fix) and `book.grabar.corrected.md` (header cleanup) when page_0557 is processed in
  the **Vol II review batch** (full-page overlay entry).
- Evidence: cycle formula `((11-pos)%7)+1` and the Julian-Easter date both resolve to Ա;
  `second_volume_index.csv`.

### E2. Garbled Grabar lines — a MIX of true noise and OCR failures on real text [OCR quality]
- **Status: OPEN — do NOT blanket-drop.** (Corrected understanding, 2026-07.)
- **Key correction:** the ~105 "garble" lines a text-only rule flags are **not all
  non-character**. Reviewing the line *images* shows two very different causes that produce
  identical-looking OCR gibberish:
  1. **Genuine non-character** — the slice has no text (ornamental dash/divider, margin bleed,
     blank speck), e.g. p458 `region_02_right/line_016,017` (a printer's rule). → safe to drop.
  2. **Real text the OCR botched** — the slice is *clean, legible text* that Tesseract mangled,
     e.g. p453 title `ԱՌԱՋԻՆ ՀԱՏՈՐ` → `ԱՍՌԱՋԶԻՆՀԱՏՈՐԸek`, the year `1915` → `nnn19011IeS5`,
     p459 `Աղօթք, Պահպանեա։` → `ԱԱԱԱԱՈղօթք…`. → **must be recovered, never dropped.**
- **Only the image distinguishes them** — from OCR text alone both look like garbage. So the
  automatic text rule (`is_ocr_garble`) is **not** a safe drop filter; it is only a *triage
  flag*. Dropping requires image confirmation (the visual gate, `build/nonchar_garble_gate.py`
  → `reports/nonchar_garble_gate.html`).
- **Root cause is OCR quality.** The corpus was transcribed with **baseline `tesseract`**,
  which (a) hallucinates on no-text slices and (b) mangles real display/heading text. The
  fine-tuned **TrOCR (`scale_500`)** already does better on both: on p458 it read the real
  line_003 correctly where Tesseract stuttered, and emitted **empty** on the true-noise
  line_016/017. Project Phase 4 (`reports/phase_4_results.md`): TrOCR fine-tune reaches 17.6%
  held-out CER and the documented bottleneck is **labeled-data quantity (~500–1000 lines)** —
  not the recipe. Failures cluster on **display/title fonts** (title page, headings)
  under-represented in the ~119 training lines.
- **Useful automatic signal:** where Tesseract garbles but TrOCR emits empty = strong "genuine
  non-character" (two models agree it's not text); where TrOCR emits real text = recoverable.
  Currently only 7 pages have TrOCR predictions.
- **Paths (see conversation):** (a) short-term — drop only image-confirmed noise, hand-fix
  high-value real-text lines (title/year/headings) in `book.grabar.corrected.md`; (b) long-term
  — label more varied data (esp. display/heading fonts) → push the TrOCR fine-tune to
  production → re-OCR. Superseded plan: the earlier "wire `is_ocr_garble` into `non_character`
  and drop 105 lines" is **abandoned** (would delete real text).

- **Chosen path — Gemini-flash VISION correction (POC validated 2026-07):** send each line
  crop image + candidate OCR to `gemini-3.5-flash`; it returns corrected Grabar, or
  `[NON-CHARACTER]` for a no-text slice — fixing OCR **and** solving the noise-drop problem in
  one pass. POC (`scratchpad/vision_correct_poc.py`) on p453 (display) + p519 (body):
  - **Quality:** near-perfect letter recovery on BOTH display and Bolorgir body; correctly
    flagged ornamental dividers as `[NON-CHARACTER]`; fixed stutters, bleed `)`, tone `գ3→գձ`.
  - **Cost:** ~$0.002/line → **~$28 for the whole 13,873-line corpus** per-line; a
    **whole-column image per call** would cut image tokens ~10× (~$3–5 total).
  - **Caveat:** the exact print **punctuation/spacing convention** is not reproduced reliably
    (adds/removes spaces around `. ։ ,`, sometimes `։`→`:`); needs a normalization post-step or
    a few-shot exemplar. Letters/content are reliable.
  - **Productionize (TODO, own session):** new pipeline stage — column-image → gemini-flash
    vision → parse per-line → write corrected Grabar + `non_character` flags → re-promote.
    Reuse `ml_vision/scripts/llm_correct.py` client (`GEMINI_API_KEY`, `PRICE_PER_MTOK`).

<details><summary>original E2 framing (superseded)</summary>

- Symptom: OCR garbage lines carry `non_character: false`, so they leak into `book.grabar.md`.
  Confirmed on Batch 1 (all flagged False):
  - p.458 `region_02_right/line_016` (`աՉմՍՉաՉմամամ…`), `line_017` (`ԱԱՎԱՉՍՉԱշ…ееее`), and
    the `"Մ. զ сՀ--IՀա-2--` separator.
  - p.459 `region_02_right/line_024` (`ՍՉԶՉմՉմշ…Ձ2Ձ…`), `line_025` (`ՍԶշ6աԶ…---=0ՁՀ`).
  - p.457 stray title-echo line `հՈՒԱԾԱՅԱՅՏՆՈՒԹԵԱՆ`.
- Root cause: the non-character detector's threshold doesn't catch these (long runs of a
  single glyph, Latin/Cyrillic bleed, punctuation-only strings). The translator already
  ignores them, so **English is unaffected** — this only pollutes the Grabar text.
- Fix (systemic): tighten the detector (e.g. flag lines that are >N% a single repeated glyph,
  contain non-Armenian letter runs, or lack any Armenian word token) → re-run OCR flagging →
  `pipeline.promote` drops them automatically corpus-wide. Until then they are dropped
  manually in `book.grabar.corrected.md`.
- Tracked as task; see also gotcha #4 (margin/column bleed).
</details>

### E3. OCR letter-doubling in real Grabar lines — Batch 1 pp.457–459 [transcription]
- **Status: FIXED in `book.grabar.corrected.md`** (Class B); English needs no change.
- p.457 & p.459: `հհհրեշտակն` → `հրեշտակն` ("the angel"); p.458: `ձձձեղ` → `ձեզ` ("to you"),
  `ՄՍՍՍղօթք` → `Աղօթք` ("Prayer"), `ժամամուտքն |րէք … յաւարն` → `… երեք … յաւուրն`.
- Evidence: adjudicated against the page grabar + the regular structure; the doubled leading
  glyph / stray bar are classic Tesseract artifacts. Pattern (leading-glyph tripling) recurs
  corpus-wide — candidate for a systemic normalization later.

---

### E4. Title page p453 Grabar mangled by Tesseract (display font) — [transcription · OCR failure]
- **Status: PROPOSED full-page correction in `book.grabar.corrected.md`** — verify orthography.
- The entire title page is large display type that Tesseract read poorly (`ՏՕՆԱՑՅՈՅՑ` for
  ՏՕՆԱՑՈՅՑ, `ԱՍՌԱՋԶԻՆՀԱՏՈՐԸek` for ԱՌԱՋԻՆ ՀԱՏՈՐ, `nnn19011IeS5` for 1915, etc.). Re-transcribed
  all 24 text lines from `data/columns/page_0453_human_region_01_single.png`, cross-checked
  against the (correct) English on the page. Two ornamental dividers (lines 20, 24) dropped as
  genuine non-character.
- This is the canonical example of E2 class (b): real text, bad OCR → recover, not drop.

## Candidate defects (from the QA pass — awaiting batch review)
Themed backlog, to be adjudicated page-by-page and promoted to "Confirmed" above. Anchors
are `## page_NNNN`.

- **Garble / nonsense:** p.462 `[Corrupted/Unintelligible lines]`; p.550 fragment collapse;
  p.569, p.606 nonsense-character markers; p.628 impossible date "0."; invented tone glosses
  p.602, p.636.
- **Missing text / cut-offs:** readings with an end but no start at column tops (p.461,
  p.480, p.488, p.508); month gaps marked `...` (p.576); a year-table with no date numbers
  (p.600).
- **Column / margin bleed** (delete per gotcha #4): stray index numerals p.559, p.585,
  p.620, p.623, p.633; merged-column debris p.488; the `[114]` float p.585.
- **Misordered / column-swap:** Mark/Luke pericope swap p.525→526; Vol II Զ saint-day order.
- **Inconsistent terms:** normalize per `GLOSSARY.md` (Hambartsi, Harts, Barekendan,
  Mankunk/Metsatsuse, Mesedi, tone codes) — corpus-wide.
- **Untranslated Armenian left in place:** concentrated pp.504, 510, 593, 598, 604, 625,
  628, 629 (and scattered elsewhere).

---

## Reprocessing candidates (need a pipeline re-run, not a hand-patch)
- **p.593 `ՂՁՉ`** — OCR hallucinated a third letter onto the leap pair ՂՁ (year-lettering is
  1 letter or a reverse-consecutive pair; gotcha #3). Fix at OCR/correction stage.
- **Column-order defects** (e.g. Զ Vol II saint days) — fix in crop/region ordering.

## Coverage items
- **Vol I pp.453–457** — ✅ promoted (2026-07, `pipeline.promote --range 453-641`): p.453
  title page, p.454 dedication, p.455 blank, p.456 opening hymn, p.457 Theophany canon.
- **Vol II pp.642–643** digitized + translated; awaiting the in-progress run + re-promote.
