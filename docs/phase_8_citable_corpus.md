# Phase 8 — the citable corpus: from "digitized" to "true to the original"

**Status:** planned · **Created:** 2026-09-20 · **Owner:** —
**Depends on:** the promoted `corpus/` (pp.453–641), Phase 5 (LLM text-correction),
Phase 6 (column detection), `docs/kraken_line_segmentation.md` (Steps 1–2).
**Consumes:** `docs/phase_7_gemini_vision_correction.md` (re-scoped here — see §5.3).
**Downstream customer:** `armenian-lectionary` — the reason this phase exists.

---

## 1. The goal, stated precisely

Publish the `armenian-lectionary` engine with **documentation behind every day's
lectionary**, such that a researcher or cleric who questions a reading selection can
follow it back to the exact rule in the Տօնացոյց it was derived from — and such that an
agent can audit those derivations for faulty logic before submission.

That goal decomposes into three capabilities, none of which exist today:

1. **A stable citation address.** Every line traceable to a page, a section (volume,
   taregir, month), and a logical entry — with an identifier that survives
   re-segmentation.
2. **Text accurate enough at the citable tokens** that a citation survives inspection.
3. **A derivation link** from each engine rule to the corpus passage that licenses it.

This phase delivers (1) and (2). It specifies (3) and hands it to `armenian-lectionary`.

---

## 2. The framing problem — the provenance is inverted

**The engine's readings are not currently derived from the Տօնացոյց.**

- `armenian_lectionary/data/lectionary_data.json` — 4,541 day-entries across 80
  keyspaces — declares `"Distilled & cross-year-validated from sacredtradition.am"`.
- `saint_schedule.json` declares `"Mined from sacredtradition.am"`.
- The book appears as ~55 free-text page comments in `engine.py` plus 10 hand-written
  `docs/sources/*.md` rubrics: **~1.4% citation coverage**, and those are *post-hoc
  justifications*, not derivations.

The repo's README is honest about this ("the canonical rubric the readings must be
derivable from"), but *derivable in principle* is not *derived in fact*. The chain of
custody runs through a website's observed outputs across 13 years, reverse-engineered
into rules. A perfect transcription would not, by itself, let a cleric check a reading.

**The corpus programme and the derivation programme are two separate efforts, and only
one is underway.** This doc plans the first and specifies the interface to the second.

### 2.1 Why this is tractable

A naive regex over Volume I extracts **958 scripture citations across 83 of 94 pages**,
with clean book abbreviations — Ղուկ (134), Յովհ (126), Եսայ (98), Մատթ (68), Մարկ (67),
Կորն (59), Առակ (40), Իմաս (35), Գործք (33), Հռոմ (30), Եբր (29) — plus 1,273 `վ. N`
verse-end markers. Volume I *prints the readings*, in a regular, parseable form:

> `Եզեկ. Դ. 16. Եւ եղեւ բան տեառն. վ. 19. ապրեցուսցես։ Առաքեալն բ. Կորն. Զ. 1.
> Գործակից եմք ձեր. վ. 14. լծակիցք անհաւատից։ Աւետարան Մատթ. ԺԲ. 22. Յայնժամ
> մատուցաւ. վ. 32. ի հանդերձելումն։`  — p.466

— i.e. Ezekiel 4:16–19, 2 Corinthians 6:1–14, Matthew 12:22–32, each with an incipit and
an explicit verse boundary. **Volume I is machine-extractable into readings.** That is
the lever that inverts the provenance: extract them, diff against the distilled table,
and sacredtradition.am becomes a test oracle *in fact* rather than only in the README.

---

## 3. Measured baseline (pp.455–615, measured 2026-09-20)

161 pages · 11,978 lines · 7 blank · 87 auto-crop / 67 human-crop.

### 3.1 Documented gaps still open

| Gap | State |
|---|---|
| Phase 7 vision correction | POC validated 2026-07, **never built** |
| `docs/ocr_approach_comparison.md` | every CER cell still `_TBD_` |
| Kraken | geometry for 195 pages (448–642) ✓; human review **19 pages**; Step-2 ops (`initials`/`merges`/`splits`/`section_titles`) **0 recorded** — all 19 reviews use the Step-1 schema; **nothing** in `pipeline/`, `build/` or `corpus/` references kraken |
| ERRATA backlog | unadjudicated; overlays cover **4 pages** (453, 457–459); `book.english.corrected.md` **empty**; `GLOSSARY.md` written, never applied |
| Vol II pp.642–643 | digitized, not promoted |

### 3.2 Undocumented gaps (found by measuring)

**(a) The citable payload is the most corrupt part of the text.** `DEFECT_MAP.md` counts
"noise" and "doubling" but never validates the liturgical token grammar:

| Token class | Corrupt | Total | Rate |
|---|--:|--:|--:|
| Tone codes (`{ա,բ,գ,դ}×{ձ,կ}`) | 268 | 979 | **27.4%** |
| Vol II weekday abbreviations | 231 | 1,515 | **15.2%** |
| Doubled-initial words | 956 | — | 5× denser in Vol II (0.15/line vs 0.03) |

The failures are **glyph-class-specific, not general illegibility**: `ձ`→`3`/`Յ`
(`գ3`×116, `բ3`×63, `դ3`×22), `կ`→`)` (`բ)`×19, `գ)`×7), `շ`→`չ` (`Բչ`×100, `Գչ`×58,
`Եչ`×39, `Դչ`×32). It reaches book names too: `Եղեկ`×4 against `Եզեկ`×9 (Ezekiel).

These are precisely the fields a lectionary citation turns on — tone, weekday,
Sunday-number — and Vol II is both the worse volume and the load-bearing one.

**(b) The text-only correction stage is not doing the work.** The `gemini-3.1-pro`
minimal-edit pass touched 16.3% of lines and rewrote **zero** lines below 0.5 similarity.
It is light smoothing, and — having no image — it left all 268 corrupt tone codes in
place even though `գ3` is not a token the vocabulary permits.

**(c) Traceability is broken for a third of the corpus.** `region_bbox` is `null` on
**4,118 of 11,978 lines (34.4%)**. For a third of citations there is no way to put the
ink in front of a skeptical reader.

**(d) There is no text unit above the line.** 3,000 lines (**25%**) end mid-word in a
hyphen and nothing dehyphenates, so full-text search misses a quarter of word
occurrences. And `lines.json` carries `page`/`region`/`column` and nothing else — **no
volume, taregir, month, day or entry field exists anywhere in the data.** `STRUCTURE.md`
holds that knowledge as prose. "Trace every line to a section" has no field to write to.

**(e) `line_id` is not a durable citation key.** It is region-relative
(`region_01_right/line_005`), and `docs/kraken_line_segmentation.md` notes that
re-generating segmentation renumbers ids on 78 pages. Any public citation minted on it
breaks on the next re-run.

**(f) Zero measured accuracy on this book.** All 161 pages carry `cer: null`. Every CER
number in the repo (4.4%/1.0% TrOCR, 4.9%/4.6% hye-calfa-n, 17.6% Phase 4) was measured
on *Ժամագիրք Ատենի* — a different book, different printing. There is no evidence base
for the phrase "true to the original."

**(g) English.** 25 of 154 content pages carry untranslated Armenian (3,291 chars);
13 explicit `[corrupt…]` markers (p568 alone has 6).

### 3.3 A correction to `corpus/ERRATA.md` E2

E2 states the corpus was "transcribed with **baseline `tesseract`**." **This is wrong.**
`pipeline/registry.py:63` and `ml_vision/scripts/predict_lines_tesseract.py:55` both use
**`hye-calfa-n`** — Calfa's historical Armenian traineddata (Classical/Western/Eastern,
including historical fonts), benchmarked in `docs/phase_2_alternatives.md` at 4.9%
(frozen) / 4.6% (page_0400) line CER zero-shot. The `tag: "tesseract"` is a label, not
the model.

This materially re-ranks the options. The corpus is not running a naive engine that a
better one would obviously beat; it is running a purpose-built historical Armenian model
at roughly 5% line CER on a comparable book, whose residual errors cluster in a **small,
enumerable set of glyph confusions**. That argues for targeted normalization and
fine-tuning over a wholesale engine swap. **Fix E2's root-cause paragraph.**

---

## 4. Tooling evaluation — Datalab, Reducto, Calfa

Assessed 2026-09-20 against this phase's needs.

### 4.1 Surya (Datalab) — **adopt for geometry and layout; evaluate for recognition**

`datalab-to/surya`. Code **Apache 2.0**; model weights under a modified AI Pubs Open
RAIL-M licence (free for research, personal use, and organisations under $5M
funding/revenue — fine here; note it if the lectionary API ever goes commercial).

- **Armenian is first-class:** `hy` appears in the 91-language table at a **90.1%** pass
  rate on Datalab's internal benchmark.
- **Line detection emits polygons** (`(x1,y1)…(x4,y4)`), axis-aligned bbox, and a
  confidence score — exactly what gap (c) needs, and a strict superset of what kraken
  was adopted for.
- **Separate layout and reading-order models** on top of detection — directly relevant to
  gap (d) and to §5.1's entry segmentation, which kraken does not address at all.
- Fine-tuning is supported (Datalab offer a paid managed stack; not required).

**This collapses two open workstreams into one.** Kraken was adopted for geometry;
Surya delivers geometry *plus* layout *plus* reading order from one actively-maintained,
Armenian-aware, Apache-2.0 project, and unlike kraken it is not confined to a dev venv.

**Caveat that must not be skipped:** 90.1% is on modern Armenian print. The Տօնացոյց is
1915 Jerusalem Bolorgir with abbreviations, Armenian numerals and display faces. That
number is a reason to *test*, not to adopt sight-unseen — and testing requires ground
truth we do not have (gap (f)). See §5.2.

### 4.2 Reducto — **no**

Reducto's parsing product is a closed commercial API. Their open-source release is
**RolmOCR** (Apache 2.0) — a `Qwen2.5-VL-7B` fine-tune on `allenai/olmOCR-mix-0225`, an
English-heavy academic-PDF corpus with no Armenian training signal. Nothing here is
targeted at our problem, and §4.4 explains why that class of model is actively risky for
it.

### 4.3 Calfa — **already in use; the under-exploited asset**

`calfa-co/hye-tesseract` (`hye-calfa-n.traineddata`) is **already the corpus's OCR
model** (§3.3). Calfa is a French project specialising in Armenian palaeography, with
published work on erkat'agir/bolorgir/nōtrgir/šłagir script identification, and
Calfa Vision — a free annotation tool with real-time fine-tuning for non-Latin scripts,
reporting >97% on bolorgir manuscripts from as few as **3 transcribed pages**.

Two consequences:

- `docs/phase_2b_hye_tesseract_finetune_plan.md` is **ready to execute and unexecuted**.
  Fine-tuning `hye-calfa-n` on in-book lines is the most direct attack on the ձ/շ/կ
  confusions of §3.2(a), because those are this printing's glyph shapes, not a general
  Armenian OCR weakness.
- The "3 pages" result suggests ground-truth cost for a *targeted* fine-tune is far lower
  than the ~500–1,000 lines Phase 4 estimated for TrOCR-from-scratch. Ground truth is
  still required for *evaluation* at publication scale (§5.2) — but the training bill is
  smaller than assumed.

### 4.4 The general-VLM warning (GlotOCR Bench, LMU Munich)

*GlotOCR Bench: OCR Models Still Struggle Beyond a Handful of Unicode Scripts*
(arXiv 2604.12978) evaluates open and proprietary VLMs across 100+ Unicode scripts.
Headline: most models perform well on **fewer than ten scripts**, and even the strongest
frontier models fail to generalise beyond thirty. Armenian (`Armn`) is in the benchmark;
per-script tables show several evaluated models scoring 0.0 on it. Surya is *not*
evaluated; RolmOCR, olmOCR and Gemini are.

The finding that matters for us is the **failure mode**, not the ranking:

> "Models confronted with unfamiliar scripts either produce random noise or hallucinate
> characters from similar scripts they already know." … "Cross-script hallucination is
> the dominant failure mode: models overwhelmingly confabulate in a wrong script rather
> than abstain."

For a citable corpus this inverts the usual risk calculus. **Tesseract garble is visibly
wrong; VLM hallucination is invisibly wrong.** A model that silently emits fluent,
plausible Grabar that is not on the page is far more dangerous to this project than one
that emits `ՍՉմՍՉ`. This is the strongest argument for the token-grammar gate (§5.3),
for keeping `ocr_raw` beside every corrected line permanently, and for not treating
Phase 7's Gemini pass — or any VLM — as self-certifying.

---

## 5. Workstreams

Ordered. W1 is the keystone; W2 gates the word "mint"; W3 and W5 can run in parallel.

### W1 — Mint the citation address *(do first; blocks everything)*

Cheapest item and the keystone: kraken/Surya geometry, corrected text, and rule
extraction all need somewhere to hang, and today there is no stable anchor (§3.2(d,e)).

**Two design decisions:**

1. **The citable unit is the *entry*, not the line.** What a cleric wants pointed at is
   one day's rubric — `13. Կիր. ԲԿ. Չորրորդ։ Հարց բկ. Որ զծառայի։ Համբ. բկ. Կանխեցին։` —
   which spans lines and sometimes columns. Lines are the OCR unit; entries are the
   citation unit. In Vol II an entry opens with a date numeral; in Vol I with a feast
   header. Both are detectable.
2. **Anchor on `volume → section → page → entry` plus a content hash — never on line
   index.** A line-index citation breaks on the next re-segmentation (§3.2(e)); a
   content-hashed entry citation survives it, and a hash mismatch is a *useful* signal
   that the text under a published citation changed.

**Build:**
- Add `volume`, `section` (taregir for Vol II, section slug for Vol I), `entry_id` and
  `entry_seq` to `lines.json`; have `pipeline.promote` populate them.
- Commit the page→section map as data. Vol II already has one
  (`armenian-lectionary/docs/sources/second_volume_index.csv`, 35 letters, pp.557–638);
  Vol I needs `corpus/STRUCTURE.md`'s prose table turned into a CSV.
- Add a dehyphenation pass producing an entry-level `text` field beside the line-level
  text (keep both — the line breaks are page evidence, the entry text is what you search
  and cite).

**Gate:** every content line in 453–641 resolves to exactly one entry; every entry
resolves to a volume + section + page; citation ids are stable across a forced
re-segmentation of a 10-page sample.

### W2 — Ground truth for *this* book *(gates the word "mint")*

There is none (§3.2(f)). Until it exists, "true to the original" is an assertion, and
there is no way to choose between hye-calfa-n, a fine-tune, Surya and Phase 7 — §4 gives
us three new candidates and no instrument to rank them.

**Build:** 300–500 hand-verified lines, stratified across Vol I body, Vol II laydown, and
display/heading faces, drawn from the pages `DEFECT_MAP.md` ranks worst *and* from clean
pages (a defect-biased sample overstates error). Store beside the existing
`data/golden/` + `data/frozen_test_set/` convention. Re-use the labeling UI.

**Gate:** a CER number for the shipped corpus on this book, split display vs. body,
written into `docs/ocr_approach_comparison.md` — the first non-`_TBD_` row.

### W3 — The closed-vocabulary normalizer *(cheapest real win; start now)*

Tone codes live in an 8-value set (`{ա,բ,գ,դ}×{ձ,կ}`) and weekdays in a 7-value set.
`գ3`→`գձ`, `բ)`→`բկ`, `Բչ`→`Բշ`, `Եղեկ`→`Եզեկ` are **deterministic** given the closed
vocabulary — no model, no guessing. ~500 tokens recovered at the exact fields §5's
customer cites.

Extend the vocabulary to the scripture book abbreviations (the Vol I list in §2.1 is
closed and short).

**Gate:** 100% of normalizer edits confirmed against line images on a random 50-token
sample; zero edits that change a token already in-vocabulary; re-run
`build/scan_defects.py` and record the drop. **Never apply a substitution where the
target is ambiguous** — the point of a closed vocabulary is that it is not guessing.

### W4 — Targeted fine-tune (Phase 2b, unblocked by W2)

Execute `docs/phase_2b_hye_tesseract_finetune_plan.md` against **in-book** lines from W2,
weighted toward Vol II and toward the ձ/շ/կ confusion set. §4.3's "3 pages" result
suggests this is cheap. This attacks the residual that W3 cannot: confusions with no
closed vocabulary to snap to.

**Gate:** CER on the W2 held-out split beats shipped hye-calfa-n, *and* the §5.3 token
grammar improves. Record in `docs/ocr_approach_comparison.md`.

### W5 — Re-scope Phase 7, and run the bake-off

Phase 7 remains the right instinct — only the image separates real text from noise — but
§4.4 changes its terms, and §4.1 adds a competitor it did not know about.

**Three changes to `docs/phase_7_gemini_vision_correction.md`:**

1. **Change the gate.** Phase 7 currently gates on CER against golden pages *from a
   different book*. Gate instead on the **token grammar**: tone codes in-vocabulary,
   weekdays in-vocabulary, dates monotone within a month, book abbreviations resolvable,
   taregir one letter or a reverse-consecutive pair (`STRUCTURE.md` gotcha #3). This is
   self-validating, needs no new ground truth, and measures exactly the fields we cite.
   Keep the W2 CER check as the *anti-hallucination* control — the grammar gate alone
   would reward a model that confabulates well-formed nonsense (§4.4).
2. **Add Surya to the comparison** as a local, free, reproducible alternative. For a
   *published* corpus this matters beyond cost: "re-runnable with open weights" is a far
   more defensible provenance claim than "we asked a hosted model in July 2026."
3. **Run Vol II (557–615) first** — worse text, and it is what the engine consumes.

**Decide, don't drift, on kraken.** Its payoff was geometry; Surya supplies geometry plus
layout plus reading order (§4.1), and the 19-page review with **zero** Step-2 ops
recorded means the Step-2 correction tooling is still unvalidated by use. Before
investing more review hours, run Surya on the same 19 reviewed pages and compare against
the existing flags — that is a free head-to-head on already-reviewed ground. Retire or
keep kraken on the result, and record it in `docs/kraken_line_segmentation.md`.

### W6 — The derivation layer *(specified here, built in `armenian-lectionary`)*

The interface this phase exists to serve.

- Build the Vol I reading extractor (§2.1) over the W1 entry units. Output:
  `entry_id → [{book, chapter, verse_start, verse_end, incipit, explicit}]`.
- Diff against `lectionary_data.json`'s 4,541 entries. Every disagreement is either an
  engine error, an OCR error, or a genuine source/oracle divergence — all three are
  findings, and the third is exactly what `dev/source_corrections.py` exists to record.
- Add a `citations` field to the engine's rule definitions and a test asserting every
  keyspace carries ≥1 citation resolving to real corpus text. Start with the 80
  keyspaces (the rule units), not the 4,541 day-entries.
- The 10 existing `docs/sources/*.md` rubrics become the template; they already do this
  by hand for the hardest cases.

**Gate:** ≥1 resolving citation per keyspace; the Vol I extractor reproduces the
distilled table on a named majority of Vol I days, with every disagreement triaged.

---

## 6. Sequencing

```
W1 (citation address) ──┬── W3 (normalizer) ──┐
                        │                      ├── W5 (bake-off: Phase 7 vs Surya vs FT)
W2 (ground truth) ──────┴── W4 (fine-tune) ────┘
                                               └── W6 (derivation layer, armenian-lectionary)
```

W1 and W2 are independent and both block the rest. W3 can start immediately — it needs
neither. W6 needs W1's entry units but not W5's re-OCR: **the derivation diff can begin
on today's text**, because a 27% tone-code error rate does not prevent scripture-citation
extraction (book abbreviations and Arabic chapter/verse numerals are a different, cleaner
glyph class). Do not serialise W6 behind a perfect corpus.

---

## 7. Risks

- **Hallucinated fluency (§4.4)** — the dominant risk to a citable corpus. Mitigations:
  keep `ocr_raw` permanently beside corrected text; the W2 CER control alongside the
  token-grammar gate; never let a VLM pass self-certify.
- **Perfectionism deadlock** — waiting for a perfect corpus before starting W6. The
  sequencing note in §6 exists to prevent this.
- **Surya licence drift** — weights are RAIL-M-with-revenue-threshold, not Apache. Fine
  today; re-check before any commercial use of the lectionary API.
- **Ground-truth sampling bias** — sampling W2 only from `DEFECT_MAP.md`'s worst pages
  would overstate corpus error and flatter any re-OCR. Stratify.
- **Entry segmentation is a new failure surface** — a wrong entry boundary produces a
  *confidently wrong* citation. Gate W1 on round-trip: every line lands in exactly one
  entry, no line orphaned.

---

## 8. Decision log

- **2026-09-20:** Reviewed pp.455–615 and measured the baseline (§3). Found the
  provenance inversion (§2) and the token-grammar corruption (§3.2(a)), neither
  previously documented. Corrected `ERRATA.md` E2's claim that the corpus used baseline
  Tesseract — it uses Calfa `hye-calfa-n` (§3.3), which re-ranks engine-swap below
  targeted normalization + fine-tune.
- **2026-09-20:** Evaluated Datalab/Surya, Reducto and Calfa (§4). **Adopt Surya** as the
  geometry/layout candidate (Armenian-supported, polygons, Apache-2.0 code) and add it to
  the Phase 7 bake-off; **reject Reducto** (closed API; RolmOCR has no Armenian signal);
  **exploit Calfa further** — `hye-calfa-n` is already shipping and Phase 2b is written
  and unexecuted. Re-scoped Phase 7's gate from cross-book CER to the token grammar plus
  an anti-hallucination CER control, on the GlotOCR finding that mid-resource-script
  failure is *confabulation*, not noise.

## 9. See also

- `docs/phase_7_gemini_vision_correction.md` — re-scoped by §5.5 (W5).
- `docs/kraken_line_segmentation.md` — the kraken decision is reopened by §4.1.
- `docs/phase_2b_hye_tesseract_finetune_plan.md` — W4.
- `docs/ocr_approach_comparison.md` — where W2/W4/W5 numbers go.
- `corpus/ERRATA.md` (E2 needs the §3.3 fix), `corpus/DEFECT_MAP.md`,
  `corpus/STRUCTURE.md`.
- Surya: <https://github.com/datalab-to/surya> · RolmOCR:
  <https://huggingface.co/reducto/RolmOCR> · Calfa hye-tesseract:
  <https://github.com/calfa-co/hye-tesseract> · GlotOCR Bench:
  <https://arxiv.org/abs/2604.12978>
