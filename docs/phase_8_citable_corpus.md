# Phase 8 — the citable corpus: from "digitized" to "true to the original"

**Status:** planned · **Created:** 2026-09-20 · **Updated:** 2026-09-21 · **Owner:** —
**Depends on:** the promoted `corpus/` (pp.453–641), Phase 5 (LLM text-correction),
Phase 6 (column detection), `docs/kraken_line_segmentation.md` (Steps 1–2).
**Consumes:** `docs/phase_7_gemini_vision_correction.md` (re-scoped here — see W5).
**Downstream customer:** `armenian-lectionary` — the reason this phase exists.

> ## ⚠️ Open decision for the maintainer — read before approving this plan
>
> **Every Armenian OCR model in the Calfa chain is CC BY-NC 4.0; `armenian-lectionary` is
> Apache-2.0.** This is a pre-existing condition, not something this plan introduces —
> the shipped corpus was already produced with `hye-calfa-n` — but the plan leans further
> into that chain, so it should be settled deliberately *before* publication rather than
> discovered after.
>
> **What needs deciding:**
> 1. Is a scholarly/ecclesial publication, and a free lectionary API, within "NonCommercial"?
>    (Model outputs are generally not derivative works of the model, but NC restricts *use*,
>    and this is a judgement call — worth confirming directly with Calfa, who have been
>    generous with open Armenian models and are the right people to ask.)
> 2. If an NC-free chain is wanted, the Apache-2.0 path exists: **kraken** (§4.7) or
>    **Surya** (§4.3) for segmentation + the **Apache-2.0 PP-OCRv6-for-kraken** recognition
>    port (§4.4). It is weaker on Classical Armenian (synthetic-only training) and would
>    cost a rebuild — so this is a real trade, not a free swap.
> 3. Does the *corpus itself* get a licence distinct from the engine's Apache-2.0?
>
> Full table and reasoning in **§4.6**. Nothing else in this plan is blocked on the answer,
> but the answer should be known before anything is published.

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

### 3.4 Phase 2b already ran, passed its primary gate, and was never recorded

`ml_vision/tessdata/hye-grabar.traineddata` exists locally (built 2026-06-20), the
training log is at `reports/phase2b_tesseract_ft_train.log` (finished at BCER train
1.189%), and both eval runs completed — their results have been sitting unread in
`reports/phase4_*_tesseract_ft.json`. Computed 2026-09-20:

| eval | zero-shot `hye-calfa-n` | **FT `hye-grabar`** | TrOCR `scale_500` |
|---|--:|--:|--:|
| frozen 100 | 4.92% | **3.54%** | 4.37% |
| page_0400 (71) | 4.56% | **1.84%** | 1.02% |

Against Phase 2b's own cheat-sheet: **primary gate passed on both** evals; stretch passed
on frozen (3.54% ≤ 4.37%), missed on page_0400 (1.84% > 1.02%). All runs are healthy
(`arm_frac` 1.00, 0 empty, non-degenerate).

**The corpus is still OCR'd with the zero-shot model.** Re-OCRing with `hye-grabar` is
local, free, already built, and worth 28% relative CER on frozen and 60% on page_0400 —
on *that* book (see the transfer caveat in §4.6).

The error analysis also corroborates §3.2(a) directly: on the FT frozen set,
lines **with** an abbreviation mark score 4.12% CER against **1.41%** for lines without —
a ~3× gap. The residual error is concentrated in exactly the compressed, ligature-like
glyph class that the tone codes and weekday abbreviations belong to.

**Actions:** write the verdict subsection into `docs/phase_2_alternatives.md` (Phase 2b
Step 5, never done), and promote `hye-grabar` to a registry entry in
`pipeline/registry.py` so it is selectable as an OCR stage.

---

## 4. Tooling evaluation — Calfa, Datalab, kraken, PaddleOCR, Reducto

Assessed 2026-09-20/21 against this phase's needs.

### 4.1 The Calfa family — the incumbent, and the under-exploited asset

Calfa is a French project specialising in Armenian palaeography, with published work on
erkat'agir/bolorgir/nōtrgir/šłagir script identification. **It already supplies the
corpus's OCR model** (§3.3). It now ships four things that matter here:

| Artefact | What it is | Status here |
|---|---|---|
| `calfa-co/hye-tesseract` → `hye-calfa-n` | Tesseract 5 traineddata, Classical/Western/Eastern Armenian incl. historical fonts | **shipping in the corpus**, zero-shot |
| `hye-grabar` (ours) | `hye-calfa-n` fine-tuned on our 500-line split | **built, gate passed, unused** (§3.4) |
| `calfa-co/hye-paddle` → `paddle-calfa-tiny` | PP-OCRv6-tiny **recognition** model, PaddleOCR inference format | **untested — the upgrade path** |
| `calfa-co/hye-open-ocr` | full pipeline: layout → reading order → recognition | **untested — see §4.2** |

**`hye-paddle` is a recognition model only** — no detector. Calfa's own framing is that
`hye-calfa-n` (Tesseract) "is the default and fastest option" while `paddle-calfa-tiny`
"provides better accuracy but slower performance." That is a documented upgrade path from
the same vendor, over the same script, for the model we already run. No published
head-to-head numbers exist on either repo, so "better accuracy" is a vendor claim, not a
measurement — but it costs nothing to test locally, and it is CPU-only.

**Licence: CC BY-NC 4.0** (see §4.6).

### 4.2 `hye-open-ocr` — the closest fit to this phase's actual problem

This is the most interesting find, because it targets W1 rather than W5.

```
image ──► LayoutEngine.analyze(image) ──► regions (reading order)
      ──► Recognizer.recognize(image, regions) ──► paragraphs → lines → words
```

- **Layout detection + reading order + recognition in one chain**, Armenian-specific.
  Layout via DocLayout-YOLO (default) or PP-DocLayoutV3; the paddle layout option is
  stated to give "tight polygons on skewed/degraded scans."
- **Output: ALTO XML v4**, plus structured JSON as *paragraphs → lines → words, with
  boxes and confidences*, plus plain text and searchable PDF.
- CPU-only; needs Python ≥3.10 and the Tesseract binary.

Two of those matter disproportionately:

**ALTO XML v4 is the right target format for a citable corpus.** It is the standard the
library/DH world already consumes for digitized text, it carries per-line *and per-word*
geometry natively, and emitting it would close gap 3.2(c) (34% null geometry) while
making the corpus citable in a form institutions can ingest without bespoke tooling. W1
should strongly consider ALTO as the interchange format rather than inventing one.

**Word-level confidence is a free triage signal.** The W3 normalizer and the W5
token-grammar gate both get much sharper when a suspect token carries a confidence score:
low-confidence + out-of-vocabulary is a near-certain OCR error; *high*-confidence +
out-of-vocabulary is the hallucination signature §4.5 warns about.

**Caveat:** the paragraph/line/word hierarchy is a *typographic* structure, not the
*liturgical* entry structure W1 needs. It gets us geometry and reading order, not entry
boundaries. W1's entry segmentation is still ours to build.

### 4.3 Surya (Datalab) — strong, but now the second option for geometry

`datalab-to/surya`. Code **Apache 2.0**; weights under a modified AI Pubs Open RAIL-M
licence (free for research, personal use, and organisations under $5M funding/revenue).

- Armenian is first-class: `hy` at a **90.1%** pass rate in the 91-language table.
- Line detection emits **polygons** `(x1,y1)…(x4,y4)`, axis-aligned bbox, and confidence.
- Separate **layout** and **reading-order** models on top of detection.
- Fine-tuning supported (Datalab offer a paid managed stack; not required).

Surya remains a serious candidate and its licence is the friendliest of the geometry
options (§4.6). But `hye-open-ocr` now beats it on domain fit — Armenian-specific
throughout, ALTO output, and built by the people whose recognition model we already
depend on. **Both belong in the W5 bake-off; neither should be adopted sight-unseen.**
Surya's 90.1% is on modern Armenian print, not 1915 Jerusalem Bolorgir with
abbreviations, Armenian numerals and display faces.

### 4.4 PaddleOCR upstream, and PP-OCRv6-for-kraken

Two distinct things, easily conflated:

- **PaddleOCR's own released models do not cover Armenian script** — stated explicitly in
  the arXiv 2608.05911 benchmark below as its reason for excluding PaddleOCR. Calfa's
  `paddle-calfa-tiny` is *their* Armenian model built on the PP-OCRv6-tiny architecture,
  not an upstream release.
- **PP-OCRv6 ported to kraken** (Zenodo 21788410 and siblings, **Apache-2.0**) covers 44
  languages across 10 scripts including Armenian, with 15 private datasets behind the
  Armenian entry. But **"Classical Armenian †" is synthetic-only**: its headline 0.06%
  CER / 0.35% WER is flagged ‡ as a purely-synthetic evaluation, and the model card says
  real-world accuracy "is probably limited," because the pangoline synthesis tool "is
  limited to approximating modern, machine-printed text."

Treat the Classical-Armenian number as meaningless for our book. The port is still worth
knowing about for one reason: it is **Apache-2.0** and it is a *kraken* recognition model,
so if kraken survives the §5 W5 decision, it drops straight in without the NC constraint.

### 4.5 What the published evidence says about Armenian OCR

**arXiv 2608.05911** (Armenian diaspora press, France; 500 pages, 3,270 region-level
annotations) is the closest published benchmark to our domain — historical Armenian
print, not modern:

| System | CER | WER |
|---|--:|--:|
| Calfa OCR (generic CRNN recognizer) | **4.0%** | 23.4% |
| CRAFT + Tesseract (Calfa) | 5.0% | 24.4% |
| Gemini 3 Flash | 6.3% | 40.4% |
| Tesseract 5 trained by Calfa | 20.5% | 48.9% |
| Tesseract 5 (default) | 22.1% | 61.7% |
| Qwen3-VL 32B-Instruct | 33.0% | 42.6% |
| Qwen2.5-VL 72B-Instruct | 37.3% | 57.4% |

Three findings, in order of consequence for us:

1. **A dedicated Armenian CRNN beats the Calfa Tesseract traineddata by ~5×** on
   historical Armenian print. We run the Tesseract flavour. This is the strongest
   external evidence that §4.1's upgrade path is real.
2. **Gemini vision is not the top performer** (6.3% vs 4.0%). Phase 7's premise — that a
   frontier VLM is *the* quality lever — does not survive contact with Armenian-specific
   evidence. It is one candidate among several, not the obvious winner.
3. **General open VLMs are unusable here** (33–37% CER).

**Transfer caveat, stated plainly:** these are full-page pipeline numbers on 20th-century
Western-Armenian newspapers. Our 4.9% for `hye-calfa-n` is on *pre-cropped single lines
at PSM 13*, a much easier task, on a different book. **The absolute numbers are not
comparable and must not be quoted as if they were.** The transferable signal is the
*ordering*, and that ordering is stable and clear.

**GlotOCR Bench** (arXiv 2604.12978, LMU Munich, 100+ Unicode scripts) supplies the
failure mode. Most models perform well on fewer than ten scripts; even frontier models
fail beyond thirty. Armenian (`Armn`) is in the benchmark; per-script tables show several
evaluated models scoring 0.0. Surya is not evaluated; RolmOCR, olmOCR and Gemini are.

> "Models confronted with unfamiliar scripts either produce random noise or hallucinate
> characters from similar scripts they already know." … "Cross-script hallucination is the
> dominant failure mode: models overwhelmingly confabulate in a wrong script rather than
> abstain."

For a *citable* corpus this inverts the usual risk calculus. **Tesseract garble is visibly
wrong; VLM hallucination is invisibly wrong.** A model that silently emits fluent,
plausible Grabar that is not on the page is far more dangerous to this project than one
that emits `ՍՉմՍՉ`. Hence: the token-grammar gate (W5), `ocr_raw` retained permanently
beside every corrected line, and no VLM pass treated as self-certifying.

### 4.6 Licensing — decide before publication, not after

| Component | Licence | Bearing on us |
|---|---|---|
| `hye-calfa-n`, `paddle-calfa-tiny`, `hye-open-ocr` | **CC BY-NC 4.0** | NC. **Already our exposure** — the shipped corpus was produced with `hye-calfa-n`. Not a new risk introduced by upgrading. |
| DocLayout-YOLO, PyMuPDF (in `hye-open-ocr`) | AGPL-3.0 | Build-time only; the lectionary API does not serve these. Would matter only if OCR ran inside the served app. |
| PaddleOCR (framework) | Apache-2.0 | Fine. |
| PP-OCRv6-for-kraken (Zenodo) | Apache-2.0 | Fine — the NC-free recognition option. |
| Surya code / weights | Apache-2.0 / mod. RAIL-M (<$5M) | Fine now; re-check before any commercial use. |
| `armenian-lectionary` | Apache-2.0 | The asymmetry to resolve. |

**The open question for the maintainer, not for this doc to settle:** an Apache-2.0
engine whose underlying transcription was produced by NC-licensed models. Model outputs
are generally not derivative works of the model, and the corpus is a scholarly/ecclesial
publication rather than a commercial product — but this should be decided deliberately,
and ideally confirmed with Calfa, *before* publication rather than after. The
Apache-2.0 PP-OCRv6-kraken port exists as the fallback if an NC-free chain is wanted.

### 4.7 kraken — the segmentation option already in hand

`docs/kraken_line_segmentation.md` recorded the original migration decision, and the work
is further along than any other segmenter here: **geometry for 195 pages (448–642)**, a
review UI, an automated rule-anchored gutter-split validated on 191 pages, and 19 pages
human-reviewed. Neural baseline segmentation, polygons, native non-text filtering,
single-step page→lines, and reading order via `polygonal_reading_order`.

Two caveats, neither fatal: nothing downstream consumes it yet (§3.1), and the Step-2
correction ops (`initials`/`merges`/`splits`/`section_titles`) have **zero** recorded
entries, so that tooling is written but unexercised.

**It stays on the table as a segmentation candidate** — W5 lists it as the first
comparison to reach for if the baseline's line detection is the weak link, precisely
because the geometry is already computed and 19 pages of human review exist to check
against. The Apache-2.0 PP-OCRv6-for-kraken recognition port (§4.4) also pairs with it,
which makes kraken the natural spine of an NC-free chain if §4.6 goes that way.

### 4.8 Reducto — no

Reducto's parsing product is a closed commercial API. Their open release is **RolmOCR**
(Apache 2.0), a `Qwen2.5-VL-7B` fine-tune on `allenai/olmOCR-mix-0225` — English-heavy
academic PDFs, no Armenian training signal. §4.5 rows 6–7 show what that class of model
does on this script.

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

### W4 — Recognition upgrade *(mostly already done; cash it in)*

Three of the four steps here are already paid for.

1. **Ship `hye-grabar` now.** It is built, its gate passed, and the corpus still runs the
   zero-shot model (§3.4). Add it to `pipeline/registry.py`, write the Phase 2b Step-5
   verdict into `docs/phase_2_alternatives.md`, and re-OCR a Vol II sample.
2. **Test `paddle-calfa-tiny`** (§4.1). CPU-only, no training, same vendor as the model
   we already trust, and Calfa's own claim is that it is more accurate than the Tesseract
   traineddata — a claim §4.5's 4.0%-vs-20.5% ordering independently supports. Cheapest
   untried lever on the board.
3. **Re-run the fine-tune on in-book lines** once W2 exists — weighted toward Vol II and
   the ձ/շ/կ confusion set. §3.4's abbreviation-mark split (4.12% vs 1.41%) says that is
   where the residual lives; §4.1's "3 transcribed pages" result says it is cheap.
   Fine-tune whichever of (1)/(2) wins, not necessarily the Tesseract one.

**Gate:** beats shipped `hye-calfa-n` on the W2 held-out split, *and* improves the W5
token grammar. Record every row in `docs/ocr_approach_comparison.md` — the tables exist
and are still entirely `_TBD_`.

### W5 — Pick one baseline, make it work, compare later

**Operating principle for this workstream: we want something that works, not a survey.**
Stand up the single strongest *simple* candidate end-to-end, measure it against W2, and
treat every other option as a later comparison to be justified by a gap the baseline
leaves. Do not run a six-way bake-off first.

**The baseline: `hye-open-ocr` (§4.2).** It is the strongest-simplest because it is the
only candidate that is *one install* covering the whole chain we need — segmentation,
reading order, recognition — rather than parts we assemble:

- **Simplest:** `pip install .`, CPU-only, no GPU, no training, one pipeline call per page.
  Every other path needs a detector bolted to a recognizer by us.
- **Strongest on domain fit:** Armenian-specific end to end, from the vendor whose
  recognition model the corpus already depends on, with `paddle-calfa-tiny` available as
  a drop-in accuracy upgrade inside the same pipeline.
- **It emits what W1 needs** — ALTO XML v4 with per-line and per-word geometry and
  confidences — which no other candidate does natively. That alone closes gap 3.2(c).

**Steps:** install → run over a 10-page Vol II sample → compare against W2 ground truth
and the token grammar → if it clears, run 453–641 and re-promote. Try `paddle-calfa-tiny`
against `hye-calfa-n` *inside* the pipeline as the one cheap variation worth taking early
(§4.1), since it is a config flag, not an integration.

**Gate:** beats the shipped corpus on the W2 held-out split *and* on the token grammar,
with ALTO geometry present for every line.

#### Comparisons, deferred until the baseline is measured

Each of these earns its turn only by addressing a specific, observed baseline failure.

| Candidate | Role | Take it up when |
|---|---|---|
| **kraken** (§4.7) — 195 pages already segmented, 19 reviewed | segmentation | baseline line detection is the weak link; the geometry is already in hand, so this is a cheap check, not a rebuild |
| **Surya** (§4.3) | segmentation + layout + reading order | baseline layout/reading order fails on the odd pages, or the NC licence (§4.6) forces an Apache-path rebuild |
| `hye-grabar` (§3.4) | recognition | free regardless — ship it under W4.1 and measure; it is not a W5 decision |
| **Phase 7 Gemini vision** (§4.5) | recognition/correction | the baseline leaves a residual on display/heading faces or on the real-text-vs-noise call that local models cannot close |

Phase 7's re-scoping still stands, whenever it is taken up:

1. **Change the gate** from cross-book CER to the **token grammar** — tone codes
   in-vocabulary, weekdays in-vocabulary, dates monotone within a month, book
   abbreviations resolvable, taregir one letter or a reverse-consecutive pair
   (`STRUCTURE.md` gotcha #3). Self-validating, needs no new ground truth, measures
   exactly the fields we cite. Keep a W2 CER check as the **anti-hallucination control**:
   the grammar gate alone would reward a model that confabulates well-formed nonsense
   (§4.5). Word-level confidence (§4.2) sharpens this — low-confidence +
   out-of-vocabulary is an OCR error, *high*-confidence + out-of-vocabulary is the
   hallucination signature.
2. **Demote it in the running order** — it is hosted and paid; the local candidates are
   free, and "re-runnable with open weights" is a stronger provenance claim for a
   published corpus than "we asked a hosted model in July 2026."
3. **Run Vol II (557–615) first** — worse text, and it is what the engine consumes.

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
W1 (citation address) ──┬── W3 (normalizer) ──────────┐
                        │                              ├── W5 (bake-off, 6 candidates)
W2 (ground truth) ──────┴── W4 (recognition upgrade) ──┘
                                                       └── W6 (derivation, armenian-lectionary)
```

**Do first, today, in this order:**

1. **W4.1 — ship `hye-grabar`** (§3.4). Built, gated, unused. Pure cash-in.
2. **W3 — the normalizer.** Needs nothing; recovers ~500 tokens at the exact fields we cite.
3. **W2 — ground truth.** Now the hard blocker: §4 hands us **six** recognition candidates
   and there is still no instrument on this book to rank any of them. Every "which engine?"
   question is unanswerable until this exists.

W1 and W2 are independent and both block the rest. W6 needs W1's entry units but **not**
W5's re-OCR: the derivation diff can begin on today's text, because a 27% tone-code error
rate does not prevent scripture-citation extraction — book abbreviations and Arabic
chapter/verse numerals are a different, cleaner glyph class (§2.1). Do not serialise W6
behind a perfect corpus.

## 7. Risks

- **Hallucinated fluency (§4.5)** — the dominant risk to a citable corpus. Mitigations:
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
- **Licence asymmetry (§4.6)** — an Apache-2.0 engine over a transcription produced by
  CC BY-NC models. Pre-existing, not introduced here, but decide it deliberately before
  publication; confirm with Calfa; the Apache-2.0 PP-OCRv6-kraken port is the fallback.
- **Cross-corpus number laundering** — §3.4's and §4.5's CER figures come from different
  books, different tasks (pre-cropped lines vs full-page) and different scripts-in-period.
  They rank options; they do not describe our corpus. Only W2 can do that. Never quote
  them as this corpus's accuracy.

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

- **2026-09-21:** Reframed W5 from a six-way bake-off to **one baseline, measured, with
  comparisons deferred** — maintainer's call: "looking for something that works... test
  the strongest, simplest baseline and evaluate extensions later." Baseline is
  `hye-open-ocr` (one install, CPU, whole chain, ALTO out). kraken, Surya, Phase 7 and
  `paddle-calfa-tiny` become comparisons, each with a named trigger condition. kraken
  recorded as a live segmentation candidate (§4.7), not a retirement question — its 195
  segmented pages and 19 human reviews make it the cheapest comparison to reach for.
- **2026-09-21:** Found `calfa-co/hye-paddle` (`paddle-calfa-tiny`, PP-OCRv6-tiny
  recognition, CC BY-NC 4.0) and `calfa-co/hye-open-ocr` (layout → reading order →
  recognition, **ALTO XML v4** + word-level boxes and confidences). Calfa states
  `paddle-calfa-tiny` is more accurate than `hye-calfa-n`; arXiv 2608.05911's
  4.0%-vs-20.5% CRNN-vs-Tesseract ordering on historical Armenian press supports the
  direction. Added both to the W5 bake-off; **W1 should target ALTO XML as the
  interchange format** rather than inventing one. Same paper measures Gemini vision at
  6.3% against a dedicated Armenian CRNN's 4.0%, which **demotes Phase 7 from presumed
  winner to one candidate of six** and moves it behind the free local options.
  Also discovered Phase 2b was already trained *and* evaluated, with its results unread
  (§3.4) — primary gate passed, `hye-grabar` unused.
- **Correction (2026-09-21):** an earlier pass concluded "no `hye-paddle` exists" from
  two web searches plus arXiv 2608.05911's line that "PaddleOCR is not included: its
  released models do not cover Armenian script." Both facts were true and the conclusion
  was still wrong — the upstream project has no Armenian model, but Calfa built one. The
  `calfa-co` GitHub org should have been listed directly. Absence of a search hit is not
  evidence of absence.

## 9. See also

- `docs/phase_7_gemini_vision_correction.md` — re-scoped by W5.
- `docs/kraken_line_segmentation.md` — the kraken decision is reopened by §4.2/§4.3.
- `docs/phase_2b_hye_tesseract_finetune_plan.md` — W4.
- `docs/ocr_approach_comparison.md` — where W2/W4/W5 numbers go.
- `corpus/ERRATA.md` (E2 needs the §3.3 fix), `corpus/DEFECT_MAP.md`,
  `corpus/STRUCTURE.md`.
- Calfa: <https://github.com/calfa-co/hye-tesseract> ·
  <https://github.com/calfa-co/hye-paddle> · <https://github.com/calfa-co/hye-open-ocr>
- Surya: <https://github.com/datalab-to/surya> · PP-OCRv6-for-kraken:
  <https://zenodo.org/records/21788410> · RolmOCR:
  <https://huggingface.co/reducto/RolmOCR>
- Armenian press OCR benchmark: <https://arxiv.org/abs/2608.05911> · GlotOCR Bench:
  <https://arxiv.org/abs/2604.12978>
