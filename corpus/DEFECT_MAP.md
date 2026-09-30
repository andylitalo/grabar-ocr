# Տօնացոյց corpus — defect map (review triage)

A **generated** ranked map of likely defects across all 182 content pages (453–641), used to
target the line-by-line review at the worst pages instead of reading every page cold. Feeds
[`ERRATA.md`](ERRATA.md) and the `non_character` fix ([`ERRATA.md`](ERRATA.md) E2).

**Regenerate:** `python -m build.scan_defects` (script: `build/scan_defects.py`). Heuristic —
Grabar: `noise` (single-glyph runs / Latin-Cyrillic bleed / punctuation-only), `doubling`
(Armenian letter tripled in a real line), `flag` (`non_character`=true). English: `arm`
(untranslated Armenian chars), `mark` (`[corrupt/…]` markers), `term` (bad glossary variants),
`tone` (hallucinated tone glosses like "A-flat"/"Fourth Side"). Counts are approximate
triage signal, not exact — confirm each during review. *(Snapshot: 2026-07.)*

## Totals (Volume I = pp.453–556 · Volume II = pp.557–641)

| Defect | Total | Vol I | Vol II |
|---|--:|--:|--:|
| Grabar noise lines | 290 | 120 | 170 |
| Grabar letter-doublings | 208 | 53 | 155 |
| `non_character` flagged | **1** | 0 | 1 |
| Untranslated Armenian (chars in English) | 4138 | 1066 | 3072 |
| English defect markers `[corrupt…]` | 14 | 5 | 9 |
| Bad term variants (glossary) | 114 | 13 | 101 |
| Hallucinated tone glosses | 94 | 0 | 94 |

**Headlines**
- **`non_character` fires essentially never** — 1 flag against 290 detected noise lines. This
  is the strongest evidence for the systemic E2 detector fix; it is the single change that
  removes the largest defect class (noise) corpus-wide.
- **Volume II (pp.557–641) is the degraded zone** on every axis — it holds ~3× the
  untranslated Armenian, ~8× the bad terms, and **100%** of the hallucinated tone glosses.
- **Term/tone normalization is a Vol II problem** → the `GLOSSARY.md` pass should run over
  Vol II (esp. pp.560–638), not Vol I.

## Top 30 pages by defect score
`score = noise·2 + doubling + markers·3 + arm/10 + terms + tone`

| pg | vol | score | noise | dbl | flag | arm | mark | term | tone |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 636 | 2 | 60 | 3 | 5 | 0 | 0 | 0 | 5 | 44 |
| 594 | 2 | 46 | 2 | 3 | 0 | 399 | 0 | 0 | 0 |
| 604 | 2 | 46 | 1 | 3 | 0 | 321 | 0 | 9 | 0 |
| 598 | 2 | 45 | 2 | 4 | 0 | 316 | 0 | 6 | 0 |
| 625 | 2 | 44 | 4 | 7 | 0 | 292 | 0 | 0 | 0 |
| 582 | 2 | 42 | 2 | 2 | 0 | 158 | 0 | 4 | 17 |
| 575 | 2 | 40 | 0 | 5 | 0 | 355 | 0 | 0 | 0 |
| 574 | 2 | 38 | 1 | 2 | 0 | 341 | 0 | 0 | 0 |
| 638 | 2 | 37 | 2 | 1 | 0 | 0 | 0 | 0 | 32 |
| 510 | 1 | 36 | 0 | 0 | 0 | 368 | 0 | 0 | 0 |
| 593 | 2 | 36 | 5 | 5 | 0 | 215 | 0 | 0 | 0 |
| 628 | 2 | 25 | 5 | 0 | 0 | 108 | 0 | 5 | 0 |
| 629 | 2 | 23 | 0 | 0 | 0 | 112 | 0 | 12 | 0 |
| 568 | 2 | 22 | 2 | 0 | 0 | 0 | 6 | 0 | 0 |
| 504 | 1 | 21 | 2 | 1 | 0 | 165 | 0 | 0 | 0 |
| 630 | 2 | 19 | 4 | 2 | 0 | 96 | 0 | 0 | 0 |
| 573 | 2 | 17 | 4 | 3 | 0 | 0 | 0 | 6 | 0 |
| 613 | 2 | 17 | 4 | 0 | 0 | 0 | 0 | 9 | 0 |
| 506 | 1 | 16 | 5 | 0 | 0 | 60 | 0 | 0 | 0 |
| 517 | 1 | 16 | 6 | 0 | 0 | 46 | 0 | 0 | 0 |
| 540 | 1 | 16 | 3 | 2 | 0 | 84 | 0 | 0 | 0 |
| 611 | 2 | 16 | 2 | 1 | 0 | 0 | 0 | 11 | 0 |
| 462 | 1 | 15 | 5 | 2 | 0 | 0 | 1 | 0 | 0 |
| 494 | 1 | 12 | 0 | 0 | 0 | 123 | 0 | 0 | 0 |
| 567 | 2 | 12 | 4 | 4 | 0 | 0 | 0 | 0 | 0 |
| 600 | 2 | 12 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| 606 | 2 | 12 | 3 | 0 | 0 | 0 | 2 | 0 | 0 |
| 609 | 2 | 12 | 1 | 2 | 0 | 52 | 0 | 3 | 0 |
| 626 | 2 | 12 | 1 | 1 | 0 | 98 | 0 | 0 | 0 |
| 627 | 2 | 12 | 0 | 1 | 0 | 76 | 0 | 4 | 0 |

## English defect-marker pages (explicit gaps / corruption to inspect)
p568 (6), p606 (2), p550 (2), p462 (1), p579 (1), p520 (1), p477 (1).

## Recommended batch order
1. **E2 detector fix first (task #6)** — removes ~290 noise lines corpus-wide in one re-promote;
   re-run this scan afterward so `noise`/`flag` columns reflect reality before hand-review.
2. **Glossary + tone-gloss normalization pass over Vol II** (esp. 636, 638, 582) — mechanical,
   high-volume, driven by `GLOSSARY.md`; strips all 94 tone glosses + 101 bad terms.
3. **Untranslated-Armenian pages** (594, 510, 575, 574, 604, 598, 625, 593, 504, 494) —
   translate the leftover hymn incipits (`(Սքանչելագործ)` etc.).
4. **Defect-marker pages** (568, 606, 550, 462, …) — inspect the `[corrupt…]` runs against the
   line images; recover or confirm-drop.
5. Remaining pages in page order (content-first).
