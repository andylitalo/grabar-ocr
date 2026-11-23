# Book structure: volumes, sections, entries and dates

**Status: planned (maintainer, 2026-11-23), nothing built.** This is the "cite" step of the
staged order (`README.md`) and the plan for roadmap §5 W1 (`citable_corpus_roadmap.md`): every
line gets a volume and a section, and after the book-wide engine run, every dated entry gets
its month and day. Sections are marked by hand and don't need OCR; entries and dates do.
Ids and the outline of sections without entries are below; W1's content hashes and
dehyphenated entry text are not planned here yet.

## Where it fits

1. Phase 9 "After the gate" (`docs/phase_9_line_segmentation_review.md`).
2. **Mark the Vol I season headings** (below). Needs only the verified lines and a small
   change to the layout tool, so it can start right after the gate.
3. The region-keyed migration (`region_keyed_data.md`), including step 4b.
4. **Assign every line its volume and section** (below), on the region-keyed records.
5. The code moves, then the book-wide OCR run (Phase 11).
6. **Months** (below), from the raw engine output as soon as the engine run ends. The
   weekday check's failures go to the labeler as text errors.
7. The hosted labeler (Phase 12), whose page search uses the section titles.
8. **Days** read from the corrected text; the Vol I entries and the outlines of the
   sections without entries; natural keys as they become known.

## Volumes

From the page ranges in `corpus/STRUCTURE.md` and the pages themselves, written down as
data, not inferred:

- **Vol I** pp.453–551: the title page and dedication (pp.453–454), then the readings.
- **p.552** blank.
- **Vol II** pp.553–639: the preface (pp.553–556), then one section per taregir from p.557.
  The last section, Ք, runs pp.638–639.
- **The Great Paschal table**: its explanation (p.640, how to read the table, which
  "is on the next page") and the table itself (p.641).
- **The colophon** and the note on how the Vol II lists were set (pp.642–643).

Front matter, the Vol II preface, the Paschal table and the colophon each get a named
section of their own, so every line belongs to exactly one section.

## Vol II sections: the taregir letters (already marked)

The review marked each taregir letter with the Title tool: `section_titles` `[{letter,
box}]` on the page, in `data/verified_lines/`. They're checked against
`armenian-lectionary/docs/sources/second_volume_index.csv` (36 rows: the 35 letters Ա–Փ with
their Julian Easter dates, plus the leap-only Ք, which has none; pages pp.557–638, and cycle
numbers):

- exactly one mark per letter, in alphabet order, each on the page the index gives;
- no letter mark outside pp.557–638.

**Checked 2026-11-23 on the review branch (`data/layout-review-517-onwards`): 36 of 36
match**, one mark each, no strays. Re-run the check when that data reaches `main`.

The verified record keeps only the mark's `letter` and `box` (the review's `source_line`
isn't carried over), so the section's first line is found by geometry: the first line after
the mark in reading order.

Once the text exists, the cycle number printed in each heading is a second check
(`cycle(pos) = ((11 − pos) % 7) + 1`, from `STRUCTURE.md`).

## Vol I sections: season headings, marked by hand

**A Vol I section is a season, opened by a display heading** (maintainer, 2026-11-23): the
large centered title under an ornamental band, such as «ԿԱՆՈՆ / ՀԱՄԲԱՐՁՄԱՆՆ ՔՐԻՍՏՈՍԻ
ԱՍՏՈՒԾՈՅ ՄԵՐՈՅ» ("Canon of the Ascension of Christ our God"). The feast or day lines inside
it (`ՀԻՆԳՇԱԲԱԹ. ՏՕՆ ՀԱՄԲԱՐՁՄԱՆ…`, opened by a drop cap) are **entries**, not sections, and
aren't marked: they're found from the text at the entry step. The old OCR has such
headings on pp.457, 497, 503, 515 and 531, and a canon title mid-page on p.462
(Presentation); the marking finds the rest. They're marked by hand in the layout tool,
which is quick:

- **The tool:** with the **Title (T)** tool, **Shift-click** a line box to mark it as a Vol I
  header; Shift-click again to unmark. (Today a click or a Shift-click in the Title tool
  both open the letter prompt, so Shift-click is free to take.) A heading that spans lines
  (`ԿԱՆՈՆ` and the line under it) gets each of its lines marked; the first starts the
  section. Nothing is typed: the heading's text comes from the OCR.
- **What it saves: not an op.** The layout tool only edits pages that are `unreviewed` or
  `fixing`, and `save_ops` sets the page back to `fixing`; ops also feed `materialize` and
  the cache and overlap hashes. So the marks get their own save path, allowed on verified
  pages: a page-level list of the marked lines' ids (e.g. `section_heads: [id, …]`),
  written to the review and to `data/verified_lines/`. It changes no geometry, ids or
  reading order, so a verified page **stays verified** and the reproduce test still holds.
  Adding the field is a format change; `rewrite_verified.py` must keep it (add it to
  `PAGE_FIELDS`) and the reproduce test must carry it.
- **Through the migration:** the list names line ids, which the region conversion maps to
  region ids along with everything else.
- **Check:** list each marked heading's page beside the Vol I table in `corpus/STRUCTURE.md`.
  The table's rows are finer than seasons (many are feasts or runs of days, i.e. entries)
  and were written from the old OCR, so the list is for the maintainer to read, not a
  pass/fail test. A season heading with no row, or a row naming a canon with no heading
  near its page, is worth a look.
- **Naming:** a section's name is filled in from the corrected text later. Its id: see
  "Ids" below.

## Assigning lines to sections (after the region migration)

Walk the book in reading order (page, then each page's `order`). A section runs from its
opening mark (a taregir letter, a Vol I season heading or a front-matter boundary) to the next one.
Every line gets `volume` and `section`. The page → section map (each section's first and
last page, and its opening line) is committed as a small CSV that can be checked by hand.

- **Gate:** every content line in pp.453–643 has exactly one section; the Vol II map agrees
  with `second_volume_index.csv`, and the maintainer has read the Vol I list against the
  `STRUCTURE.md` table.

## Entries, months and days (after the book-wide engine run)

**Entries** are the citation unit. In Vol II an entry opens with a day numeral (`24.`); in
Vol I with a feast header. The old OCR has about 1,800 numbered Vol II entries (lines
starting `N.` on pp.557–639).

**Months come from the raw engine output, before correction** (maintainer, 2026-11-23). The
engines read literally, while the corrector may normalize a garbled header or invent one,
and the raw output exists as soon as the book-wide engine run ends, so months don't wait for
correction or the labeler. The month is a header line between entries (`Յունուար։`) and
applies to the entries after it; the day is printed on each entry.

**A section's order verifies its headers.** Each common-year section has 13 month runs in a
known order (January from the 6th, February … December, January 1–5: see the rules below;
Ք has only January and February), so the search never asks "which month is this?", only
"is this the next one?":

1. **Header text.** Walking the section in reading order, the next header is a short,
   standalone line whose raw text, in **either** engine, after stripping punctuation and
   folding case, is close to the **expected next** month's name (nominative). The order
   does the disambiguating, so "closer to it than to any other month" is not required
   (Յունիս and Յուլիս are one letter apart). Set the distance on the first sections of
   the new engine output, not the old OCR: on p.560 the old OCR's `ՅՅՅունուար` is 2 edits
   from Յունուար, but the same page's `ԳԾԵՏրուաջ` (3 from Փետրուար), `ՄՄարշջջջ`,
   `ԱԱԱԱԱրիՍւշշ` and `ՄՄայիսրստստստս` are far further. Month headers are set in a display
   face, which reads worse than the body.
2. **The weekdays fit.** The entries after the header pass the weekday check (below) in the
   expected month, and would fail it in the current one.

A header is **verified** when both hold. The day numbers support it but can't decide it:
within a month they rise, so **a drop with no header near it** (30 → 2) means a missing
header or a misread numeral. A header, though, needn't sit at a drop: entries are sparse,
and on p.560 (section Բ) February ends at the 14th and March starts at the 23rd.

**Anchors.** Each section's first header follows its taregir mark (no previous run). Its
Easter entry (`Զատիկ`, a Sunday) sits at the index's Julian Easter date, in the March run
for Ա–Ժ and the April run for Ի–Փ, which pins those two headers.

**A section whose headers all verify, in order, is accepted without review**, and each
entry's month is the one its two bracketing headers give. The report counts, per section,
headers verified out of the expected number, and in total the sections and entries accepted
this way. Only sections with an unverified header go to the maintainer, with the crops of
the candidate lines; the expectation is a handful.

**Days, and the weekday check.** Each entry prints its weekday: `Կիր.` Sunday, `Բշ.` Monday,
`Գշ.` Tuesday, `Դշ.` Wednesday, `Եշ.` Thursday, `Ուր.` Friday, `Շբ.` Saturday. The OCR
confuses `շ` with `չ`: fold them in the weekday token only, since the tone code after it
(`ԲՉ.`, `ԱԿ.`) uses `Չ` as a letter. Feast days spell the weekday out in capitals
(`ԿԻՐԱԿԷ`, `ԵՐԿՈՒՇԱԲԱԹ`, `ԵՐԵՔՇԱԲԱԹ`, `ՉՈՐԵՔՇԱԲԱԹ`, `ՀԻՆԳՇԱԲԱԹ`, `ՈՒՐԲԱԹ`, `ՇԱԲԱԹ`;
confirm the spellings on the first sections). A section's taregir fixes its Julian Easter
date, and Easter is a Sunday, so every date in the section has a computable weekday.

- **With the month settled by verified headers, a failing weekday means the day numeral or
  the weekday was misread** (the old OCR's `114.` for 14 on p.560). That's a text error for
  the OCR review (the labeler), not a date question. The day is read from the corrected
  text once it exists.
- **The weekday also backs up the month**: an entry put in the wrong month almost never
  matches, so a section whose weekdays fail across a whole month points at a wrong header.

A last, independent check: `armenian-lectionary`'s `second_volume_cycles.json` maps
(taregir, date) → saint, built from the earlier human-corrected text. A matching saint at
the assigned date confirms it. Read it only; never re-run the script that builds it.

**Evidence** (p.560, old OCR, sections Ա → Բ): Dec 24 `Եչ` Thursday, 27 `Կիր` Sunday and
30 `Դչ` Wednesday fit Ա's calendar (Easter Mar 22), and so do Jan 2 `Շբ` Saturday to Jan 5
`Գշ` Tuesday. "29. Դչ" (Wednesday) can't sit next to 30 Wednesday: the check flags the entry
where the day or the weekday was misread. Section Բ (Easter Mar 23) opens with Jan 6
`ԵՐԿՈՒՇԱԲԱԹ` Monday and prints Easter at `23. Կիր.` in its March run, as computed.

**Rules to build in:**

- **The church year runs Jan 6 → Jan 5.** A section's month order is Jan (from the 6th),
  Feb … Dec, then Jan 1–5, ending at `Վերջ տարւոյն` ("end of the year"); January appears at
  both ends. Weekdays run on continuously across Dec 31. Seen at the Ա → Բ junction on
  p.560; confirm it holds for every section. A header that repeats the current month (at
  a page or column top, if the book does that) is not a new run; check on the first
  sections.
- **Each section's weekdays come from its own letter.** On p.560, Jan 2–5 close section Ա and
  Jan 6 opens Բ with a different calendar.
- **Leap years.** A leap year uses a two-letter taregir, a reverse-consecutive pair (`ԹԸ`):
  the higher letter (Թ) serves Jan 6 → end of February and the lower (Ը, the year's Easter)
  serves from March (preface §Third;
  `armenian-lectionary/docs/sources/second_volume_leap_rules.md`). Because the extra day
  falls at the end of February, the higher letter's Jan–Feb weekdays are the leap year's,
  so **every section is laid out as a common year** and the weekday check holds for all of
  it. The inline leap instructions are text, not layout; they may name months in the
  genitive (`փետրուարի`) and must not be taken for headers (the "standalone line" rule).
- **Ք is leap-only and short.** It serves only Jan 6 → end of February, for the leap year
  whose Easter is Փ's (Apr 25), so it has only January and February runs, not 13.
  Its weekdays are those of a common year with Easter on Apr 26 (Jan 6 a Tuesday:
  `6. ԵՐԵՔՇԱԲԱԹ` on p.638). From Jan 31 it lists saints normally kept after the
  Transfiguration («Ի Թադէոս առաքելոյս սկսեալ…»); they're still dated by their Ք entries.
- **Store `(taregir, month, day)`, a Julian date within a year-type,** never a civil date.
  Converting it to a Gregorian date for a given year goes through the Paschal table when the
  date is used (`STRUCTURE.md`, gotcha 1).
- **Vol I** has no running month headers. Fixed-feast dates are in the feast headers
  (`Մարտի 25`, the month in the genitive), and are read at the entry step with the same
  12 names in their genitive forms.

**Gate:** every Vol II entry has a month (from verified headers, or the maintainer's choice
for the section) and a day that passes the weekday check or was corrected in review; every
entry resolves to a volume, section and page.

## Ids: region ids now, natural keys when we have them (maintainer, 2026-11-23)

Every section, outline node and entry gets an id from the region id of its first line as
soon as it exists, so nothing waits. A region id is a hash of the line's boundary, so it
changes if the line is re-drawn. **Natural keys are added beside it as they become
known**, and are the ids to cite once they exist:

- a Vol II section: its taregir letter (at section assignment);
- a Vol II entry: `(taregir, month, day)` (after the months; unique within a section, since
  January's two runs cover disjoint days);
- a Vol I section, outline node or entry: a slug from its corrected heading, or
  `(parent, ordinal)` where there is none (after correction).

The region id stays as an alias, so an early reference still resolves. W1's
re-segmentation test applies to the natural keys.

## Sections without entries: a nested outline (maintainer, 2026-11-23)

Not every section is a run of entries. The title pages, the Vol II preface (§First …
§Seventh), the Paschal table and its explanation, and the colophon have their own shapes,
and some have subsections. So a section's content is an **outline**: a tree of nodes, each
with a `kind`, an optional heading and its lines, and children. The kinds and depth are
chosen per section; no section has to share another's schema. A section made of entries
is just an outline whose leaves are entries.

- The outline is a small hand-checked file per section (or one file for all of them),
  written from the corrected text; the kinds are named where they're first used
  (`preface_part`, `table`, `note`, …) and listed in one place so they stay consistent.
- Lines inside a node are given by their ids in reading order; a node's text is read from
  its lines, never stored a second time.

**Gate (W1's, updated to match in `citable_corpus_roadmap.md`):**
every content line in pp.453–643 resolves to exactly one leaf: an entry, or a node of its
section's outline; every leaf resolves to a volume, section and page.
