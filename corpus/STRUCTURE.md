# Տօնացոյց (Tōnatsooyts) — Structure & Master Index

**Read this first.** This is the guide to the digitized Armenian lectionary
(*Tōnatsooyts*, the Calendar/Typikon of the Armenian Church, 4th Jerusalem ed. 1915) held
in this `corpus/`. It explains the book's two-volume structure, indexes every section to a
page, and links out to the deeper liturgical canons. An agent that reads this file can
answer where any reading, feast, or year-type rule lives and how to trace it to the source.

- Text: [`book.english.md`](book.english.md), [`book.grabar.md`](book.grabar.md)
  (both `## page_NNNN`-anchored, page order).
- Corrections: [`book.english.corrected.md`](book.english.corrected.md),
  [`book.grabar.corrected.md`](book.grabar.corrected.md) — **line-level patches** over the
  pristine machine output; apply them on top of `book.*.md`. Every patch traces to `ERRATA.md`.
- Registries: [`ERRATA.md`](ERRATA.md) (our digitization/translation defects),
  [`TYPOS.md`](TYPOS.md) (typos in the *printed source*), [`GLOSSARY.md`](GLOSSARY.md)
  (controlled term renderings), [`DEFECT_MAP.md`](DEFECT_MAP.md) (generated defect triage,
  worst pages first).
- Index/provenance: [`manifest.json`](manifest.json); mechanics in [`README.md`](README.md).

---

## ⚠️ Gotchas — read before using the text
*(from `../docs/andys_notes.md`; these repeatedly tripped up prior LLM work)*

1. **The taregir (year-letter) is a JULIAN code.** It encodes the *Julian* Easter date.
   You **must** map it to the Gregorian calendar before applying it to a modern date. A
   mismatch between this book and a modern calendar is almost always *your* Julian→Gregorian
   application error — **not** a historical discrepancy in the source. Verify before
   declaring any inconsistency "unresolvable." See
   [`../../armenian_lectionary/docs/sources/great_paschal_cycle_index.md`](../../armenian_lectionary/docs/sources/great_paschal_cycle_index.md).
2. **Both volumes are digitized and present here** (see below). Do not wait for or assume a
   missing "First Volume" — it is in this corpus (from p.458).
3. **Year-lettering is strictly one letter, or a reverse-consecutive descending pair**
   (leap years, e.g. Թ+Ը → ԹԸ). Any other combination (e.g. the OCR'd `ՂՁՉ` on p.593) is an
   **OCR hallucination** — flag it, don't interpret it.
4. **Margin notes were intentionally excluded** from digitization. Stray fragments, isolated
   index numbers, or a scripture reference injected mid-sentence are **crop/column bleed**,
   not content. Treat them as defects (log in `ERRATA.md`), not text.
5. **Column ordering can still be wrong** in places (e.g. the Զ saint-day sequence in Vol II).
   If the day-by-day flow breaks, suspect a left/right column swap.

---

## The two volumes

The Tōnatsooyts is in **two volumes**, both digitized here:

| Volume | What it is | Pages (printed) | In this corpus |
|--------|-----------|-----------------|----------------|
| **Volume I** | The **temporal/festal cycle** — the actual readings (Tone, Psalm, Prophet, Apostle/Epistle, Gospel, Alleluia, Litany, Prayer) for the moving and fixed feasts of the year. Opens with the title page + dedication (p.453–454). | ~453–551 | **pp.453–551** ✓ |
| **Volume II** | The **per-taregir skeleton calendar** — one section per year-type (Easter date), giving each day's weekday, tone, Sunday-number, and saint/feast identity. **Carries no readings** — every entry says "See the First Volume." | ~553–641 | pp.553–641 |
| **Appendix** | The **532-year Great Paschal table** (year → taregir + veradir). | **p.641** | transcribed as a CSV (see below) |

**How they work together:** Volume II tells you *which* feast/saint falls on a given date in
a given year-type; Volume I tells you *what to read* for that feast. To resolve a modern
date: civil year → taregir+veradir (Paschal table) → that year-type's Vol II section → the
day's feast identity → Vol I readings — mapping Julian→Gregorian throughout (gotcha #1).

---

## Volume I — section index
*(anchors are `## page_NNNN` in `book.english.md`; boundaries are approximate to the page)*

| Section | Page(s) | Deeper canon |
|---------|---------|--------------|
| **Title page** — "Directory of Feasts [Tonatsuyts], First Volume" | p.453 | |
| Dedication / colophon (under Catholicos George V) | p.454 | |
| *(blank)* | p.455 | |
| Opening Nativity hymn ("A new king was born in Bethlehem…") | p.456 | |
| **Canon of the Theophany & Birth of Christ** (Jan 6 vigil begins); Blessing of Water | 457–458 | |
| Theophany octave (Jan 6–13); Nativity/Circumcision (8th day) | 458–459 | [nativity-octave](../../armenian_lectionary/docs/sources/tonatsooyts-nativity-octave.md) |
| Post-octave inserted saints (John Forerunner, Anthony, Theodosius…) | 460–462 | |
| Presentation of the Lord / Tearnendaraj (Candlemas, Feb 14) + eve | p.462 | [presentation-theotokos](../../armenian_lectionary/docs/sources/tonatsooyts-presentation-theotokos.md) |
| Fast of the Catechumens (Arachavor) & pre-Lent martyr cohort | pp.464–465 | [prelent-cohort](../../armenian_lectionary/docs/sources/tonatsooyts-prelent-cohort.md), [fast-of-catechumens](../../armenian_lectionary/docs/sources/tonatsooyts-fast-of-catechumens.md) |
| Eve of Great Lent (Bun Barekendan); Great Lent begins | p.466 | |
| Lenten Sundays & weekday ferias | 466–470 | |
| Lazarus Saturday | p.470 | |
| Palm Sunday (Tsaghkazard) | p.471 | |
| Holy Week (Great Mon–Fri) | 473–480 | |
| Easter Vigil & Sunday (Zatik) | p.480 | |
| Eastertide (the Fifty Days); four-Gospel continua; Annunciation; Low Sunday/Antasdan | 484–499 | [eastertide-gospels](../../armenian_lectionary/docs/sources/tonatsooyts-eastertide-gospels.md), [annunciation-canon](../../armenian_lectionary/docs/sources/tonatsooyts-annunciation-canon.md), [low-sunday-antasdan](../../armenian_lectionary/docs/sources/tonatsooyts-low-sunday-antasdan.md) |
| Ascension ("Second Palm Sunday") | p.498 | |
| Pentecost | 504–506 | |
| Post-Pentecost saints' cycle (Hripsime, Gregory the Illuminator, Etchmiadzin, Constantine/Helena…) | 506–548 | |
| Fasts of Transfiguration / Assumption / Nativity — "no feasts are held" | 512, 519, 549 | [fast-suppression](../../armenian_lectionary/docs/sources/tonatsooyts-fast-suppression.md) |
| Nativity (Advent) Fast | 549–551 | |

---

## Volume II — the per-taregir laydown

The laydown begins after the blank p.552 and a short **preface** (~pp.553–556: the leap
exceptions §Third, saint-group merges §Sixth, and the finite floating-feast list §Seventh),
then **one section per year-type**, in Armenian-alphabet order **Ա … Ք** starting at
**p.557**. Each section is headed by its **year-letter** and its **"Septenary of the Romans"
cycle number (1–7)**, then walks the calendar Jan→Dec giving each day's weekday · tone ·
Sunday-number · saint/feast.

**Do not re-derive the letter→date→page mapping — it is already indexed** in
[`../../armenian_lectionary/docs/sources/second_volume_index.csv`](../../armenian_lectionary/docs/sources/second_volume_index.csv)
(`taregir, easter_md_julian, page, cycle`; 35 letters Ա–Ք, pp.557–638) with its explanation in
[`second_volume_index.md`](../../armenian_lectionary/docs/sources/second_volume_index.md).

- **Cycle number** is a closed form of the letter position: `cycle(pos) = ((11 - pos) % 7) + 1`
  (anchored Ի=1). Use it — plus the section's stated Easter date — to **validate** that a page
  is attached to the right letter. (Validator: `armenian_lectionary/dev/second_volume_index.py`.)
  - *Known defect:* the header of **p.557** (taregir **Ա**, Easter Mar 22, cycle 4) prints
    the letter as `[Gg - Գ]` — a mislabel; its cycle (4) and its March-22 Easter row both
    confirm it is **Ա**. Logged in `ERRATA.md`.
- **Leap years** carry a two-letter (reverse-consecutive) taregir and skip a saint that was
  already kept before Feb 29. Rules:
  [`second_volume_leap_rules.md`](../../armenian_lectionary/docs/sources/second_volume_leap_rules.md).
  The **36th type Ք** (p.638) is leap-only, sharing Փ's Easter.

## Appendix — the Great Paschal cycle (p.641)
The 532-year perpetual table (civil year → **taregir** + **veradir/epact**) is transcribed as
[`../../armenian_lectionary/docs/sources/great_paschal_cycle_index.csv`](../../armenian_lectionary/docs/sources/great_paschal_cycle_index.csv)
(years 1909–2079), explained in
[`great_paschal_cycle_index.md`](../../armenian_lectionary/docs/sources/great_paschal_cycle_index.md).
*(p.641 is NOT blank — the table lives in that CSV.)*

---

## Traceability — from a passage back to the source
Per-page provenance is in `pages/page_NNNN.lines.json` (and summarized in `manifest.json`):
```
page image  data/pages/N.pdf
  → region boxes   data/columns/boxes/page_NNNN_{auto|human}.json   (committed geometry)
  → line images    data/lines/page_NNNN_*/<region>/line_NNN.png
  → OCR (raw)      lines[].ocr_raw
  → Grabar (final) lines[].grabar        →  book.grabar.md
  → English        page-level `english`  →  book.english.md
```
**English is page-atomic** (the translator reads the whole page), so there is no per-line
English. To align a specific English sentence to a line, match it against the ordered
`lines[]` grabar in that page's `.lines.json`.

---

## Coverage
191 pages, **453–643**, **0 gaps**; 7 blank pages (455, 481, 495, 501, 521, 529, 552) are
marked blank in the source, not missing. pp.642–643 (promoted 2026-09-30) are the printer's
**colophon** (Յիշատակարան of the fourth Jerusalem printing) and an editorial note on how the
Volume II taregir lists were set — no liturgical content.

## How to use this corpus (for a future agent)
1. Need **readings** for a feast → Volume I (section index above).
2. Need a **date's feast/saint identity** in a given year → Volume II section for that
   year-type (find the letter via the Paschal-cycle CSV, then the page via
   `second_volume_index.csv`).
3. Always **map the Julian taregir to Gregorian** before comparing to a modern calendar
   (gotcha #1).
4. Prefer `book.*.corrected.md`; consult `GLOSSARY.md` for term meaning, `ERRATA.md` /
   `TYPOS.md` for known defects.
