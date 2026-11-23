# Book structure: volumes, sections, entries and dates

**Status: planned (maintainer, 2026-11-23), nothing built.** This is the "cite" step of the
staged order (`README.md`) and the plan for roadmap §5 W1 (`citable_corpus_roadmap.md`): every
line gets a volume and a section, and after the corrected OCR, every dated entry gets its
month and day. Sections are marked by hand and don't need OCR; entries and dates do.

## Where it fits

1. Phase 9 "After the gate" (`docs/phase_9_line_segmentation_review.md`).
2. **Mark the Vol I section headers** (below). Needs only the verified lines and a small
   change to the layout tool, so it can start right after the gate.
3. The region-keyed migration (`region_keyed_data.md`), including step 4b.
4. **Assign every line its volume and section** (below), on the region-keyed records.
5. The code moves, then the book-wide OCR run (Phase 11), then the hosted labeler (Phase 12),
   whose page search already uses the section titles.
6. **Entries, months and days** (below), once the corrected text exists.

## Volumes

From the page ranges in `corpus/STRUCTURE.md`, written down as data, not inferred:

- **Vol I** pp.453–551: the title page and dedication (pp.453–454), then the readings.
- **p.552** blank.
- **Vol II** pp.553–640: the preface (pp.553–556), then one section per taregir from p.557.
- **The Great Paschal table** (p.641) and the **colophon** (pp.642–643).

Front matter, the Paschal table and the colophon each get a named section of their own, so
every line belongs to exactly one section.

## Vol II sections: the taregir letters (already marked)

The review marked each taregir letter with the Title tool: `section_titles` `[{letter,
box}]` on the page, in `data/verified_lines/`. Before using them, check them against
`armenian-lectionary/docs/sources/second_volume_index.csv` (36 letters Ա–Ք, their pages
pp.557–638, Julian Easter dates and cycle numbers):

- exactly one mark per letter, in alphabet order, each on the page the index gives;
- no letter mark outside pp.557–638;
- **p.557 prints `Գ` for `Ա`** (a misprint, logged in `corpus/ERRATA.md`). Decide how its mark
  records it: the section is Ա either way.

Once the text exists, the cycle number printed in each heading is a second check
(`cycle(pos) = ((11 − pos) % 7) + 1`, from `STRUCTURE.md`).

## Vol I sections: header marks (maintainer, 2026-11-23)

Vol I's sections (feasts, seasons) open with header lines, not single letters. They're marked
by hand in the layout tool, which is quick:

- **The tool:** with the **Title (T)** tool, **Shift-click** a line box to mark it as a Vol I
  header; Shift-click again to unmark. A header that spans lines gets each of its lines
  marked; the first starts the section. Nothing is typed: the header's text comes from the
  OCR.
- **What it saves:** one op naming the line, and on the verified line record a field such as
  `section_head: true`. It's an annotation, like `section_titles`: it changes no geometry,
  ids or reading order, so a verified page **stays verified** and the reproduce test still
  holds. Adding the field to `data/verified_lines/` is a format change
  (`rewrite_verified.py`).
- **Through the migration:** the field rides on the line record, so the region conversion
  carries it unchanged.
- **Check:** every row of the Vol I table in `corpus/STRUCTURE.md` has a marked header on its
  page, and every marked header falls in some row. Disagreements are listed for the
  maintainer; the table was written from the old OCR and can be wrong.
- **Naming:** a section's id is its first header line's id (its region id after the
  migration). Its name is filled in from the corrected text later.

## Assigning lines to sections (after the region migration)

Walk the book in reading order (page, then each page's `order`). A section runs from its
opening mark (a taregir letter, a Vol I header or a front-matter boundary) to the next one.
Every line gets `volume` and `section`. The page → section map (each section's first and
last page, and its opening line) is committed as a small CSV that can be checked by hand.

- **Gate:** every content line in pp.453–643 has exactly one section, and the map agrees
  with `second_volume_index.csv` and the `STRUCTURE.md` table, or each disagreement is
  explained.

## Entries, months and days (after the corrected OCR)

**Entries** are the citation unit. In Vol II an entry opens with a day numeral (`24.`); in
Vol I with a feast header. The old OCR has about 1,700 dated Vol II entries.

**Months and days.** The day is printed on each entry. The month is a header line between
entries (`Յունուար։`), and is assigned to the entries that follow it. Headers are where OCR
goes wrong (the old OCR read `ՅՅՅունուար` on p.560), so the month comes from three
independent signals, and only their disagreements reach a person:

1. **The header text.** A short line on its own, matched against the 12 month names in
   their header form (nominative), allowing an edit distance of about 2 after folding. Only
   short, standalone lines qualify.
2. **The day numbers restart.** Within a month they rise; a drop (30 → 2) is a month
   boundary. This finds every boundary without reading the header. A drop with no header
   near it, or a header with no drop, is flagged.
3. **The weekday checks every entry.** Each entry prints its weekday: `Կիր.` Sunday,
   `Բշ.` Monday, `Գշ.` Tuesday, `Դշ.` Wednesday, `Եշ.` Thursday, `Ուր.` Friday, `Շբ.`
   Saturday (the OCR confuses `շ` with `չ`: fold them; feast days spell the weekday out
   in capitals, e.g. `ԵՐԿՈՒՇԱԲԱԹ`). A section's taregir fixes its Julian Easter date, and
   Easter is a Sunday, so every date in the section has a computable weekday. An entry
   in the wrong month almost never matches. A misread day numeral fails the same check,
   which protects the digits OCR most often gets wrong.

A fourth, independent check: `armenian-lectionary`'s `second_volume_cycles.json` maps
(taregir, date) → saint, built from the earlier human-corrected text. A matching saint at
the assigned date confirms it. Read it only; never re-run the script that builds it.

**The procedure,** per section: walk the entries in reading order, carrying the current
month. At each drop in the day numbers, the next month in the section's order starts; the
header names which, and the weekday confirms each entry. Entries where every signal agrees
are accepted. The rest go to a review queue that shows the line crops (expected: a few dozen
for the whole volume), and the maintainer's choice is recorded.

**Evidence** (p.560, old OCR, sections Ա → Բ): Dec 24 `Եչ` Thursday, 27 `Կիր` Sunday and
30 `Դչ` Wednesday fit one calendar, and so do Jan 2 `Շբ` Saturday to Jan 5 `Գշ` Tuesday.
"29. Դչ" (Wednesday) can't sit next to 30 Wednesday: the check flags the entry where the
day or the weekday was misread.

**Rules to build in:**

- **The church year runs Jan 6 → Jan 5.** A section's month order is Jan (from the 6th),
  Feb … Dec, then Jan 1–5, ending at `Վերջ տարւոյն` ("end of the year"); January appears at
  both ends. Weekdays run on continuously across Dec 31. Seen at the Ա → Բ junction on
  p.560; confirm it holds for every section.
- **Each section's weekdays come from its own letter.** On p.560, Jan 2–5 close section Ա and
  Jan 6 opens Բ with a different calendar.
- **Leap years.** A leap year uses a two-letter taregir (`ԹԸ`), with inline instructions
  (preface §Third; `armenian-lectionary/docs/sources/second_volume_leap_rules.md`). Ք is
  leap-only. Assume each section is laid out as a common year, except Ք as a leap year,
  and confirm that on the first two sections before trusting the check in Jan–Feb.
- **Store `(taregir, month, day)`, a Julian date within a year-type,** never a civil date.
  Converting it to a Gregorian date for a given year goes through the Paschal table when the
  date is used (`STRUCTURE.md`, gotcha 1).
- **Vol I** has no running month headers. Fixed-feast dates are in the feast headers
  (`Մարտի 25`, the month in the genitive), and are read at the entry step with the same
  12 names in their genitive forms.

**Gate:** every Vol II entry has a month and day, with every signal agreeing or the
maintainer's choice recorded; every entry resolves to a volume, section and page.
