# Տօնացոյց (Tōnatsooyts) — Translation Glossary

A **controlled vocabulary** for the recurring liturgical terms in this corpus. The
Gemini-3.5-flash translation rendered these terms inconsistently — the same word appears a
dozen different ways — which is the single largest source of noise in `book.english.md`.
This file fixes one canonical English rendering per term, records the grabar it comes from,
and lists the **wrong variants to replace** (with page anchors) so a reviewer/agent can
normalize the text into `book.english.corrected.md`.

**Guiding principle:** adopt the **rendering Gemini already used most often** as the single
canonical form, keep the `[Bracketed]` transliteration anchor, and normalize the long tail of
one-off variants to it. **Do not impose a new scholarly romanization now** — that is deferred
until a scholar is consulted. The only renderings to *delete outright* are hallucinated ones
with no basis in the source (musical keys, invented mode names). Anchors are `## page_NNNN`
headers in `book.english.md`.

See also: [`STRUCTURE.md`](STRUCTURE.md) (master index), [`ERRATA.md`](ERRATA.md)
(defect registry), [`TYPOS.md`](TYPOS.md) (printed-source typos).

---

## Liturgical hymn/element terms

### Harts — the Fathers' hymn (Հարց)
The hymn "of the Fathers," a hymn slot in the office. By far the most frequent term
(**663×** as `[Harts]`, plus `[Harst]` misspellings **46×**).

- **Canonical:** `Canticle of the Fathers [Harts]` — Gemini's dominant full form (63×;
  "Canticle" alone, 122×, is the same rendering truncated by an adjacent clause).
- **Grabar:** Հարց ("of the fathers"), e.g. «Աստուած հարցն մերոց» ("God of our fathers").
- **Replace these wrong renderings:**
  - `Question [Harts]` — mistranslation (reads Հարց as "question"). *(e.g. Vol II tables)*
  - `Canticle of the Steps [Harts]` — conflates with the Gradual. *(e.g. page_0602)*
  - `Patristic Hymn` / `Patristic [Harts]` — normalize to the canonical. *(page_0462, page_0468, page_0460)*
  - `Father` / `Father's Song`, `Patres`, `Patrum` — normalize. *(page_0488, page_0507)*

### Hambartsi — the Elevation (evening) hymn (Համբարձի)
The evening "elevation/lifting-up" hymn. **474×** as `[Hambartsi]`.

- **Canonical:** `Evening Hymn [Hambartsi]` — Gemini's dominant rendering (121×).
- **Note:** `Dismissal Hymn` (79×) is Gemini's other frequent form; whether Hambartsi is
  properly "evening" vs. "dismissal" here is a scholarly question — **deferred**. For now
  normalize the *one-off* variants below to `Evening Hymn`; leave `Dismissal Hymn` pending
  scholar review (flag, don't force).
- **Replace these one-off renderings:**
  - `Hymn of the Ascent` / `Song of the Ascent` *(page_0471, page_0611)*
  - `Hymn at Evening` / `Evening Discharge Hymn` / `Hymn of the Evening` *(page_0474, page_0490)*
  - `Nocturn`, `Hesperis`, `Responsorial`, `Hymn of the Dwelling`, `Processional`,
    `Lord I Have Cried Hymn`, `Resurrection Night Office Hymn` *(page_0634, page_0574, page_0591, page_0598, page_0629)*

### Mankunk vs Metsatsuse — DO NOT both become "Magnificat"
Two **distinct** hymns the translation wrongly collapses into "Magnificat" (**83×**).

- **Metsatsuse (Մեծացուսցէ)** = the **Magnificat** proper, Luke 1:46 "My soul *magnifies*
  the Lord." → **Canonical:** `Magnificat [Metsatsuse]`. *"Magnificat" here is CORRECT.*
- **Mankunk (Մանկունք)** = "the **Youths**," the Song of the Three Children / Benedicite
  (Daniel 3), **not** the Magnificat. **62×** as `[Mankunk]`. → **Canonical:**
  `Hymn of the Youths [Mankunk]` (a.k.a. Benedicite). *Never render as "Magnificat."*
- **Watch for:** stacked/ambiguous pairs like `Magnificat [Metsatsuse]` directly above
  `Magnificat [Mankunk]` (e.g. page_0525) — the second is the error.

### Mesedi — the Gradual (Մեսեդի)
The gradual psalm-verse (prokeimenon). Spelled inconsistently.

- **Canonical:** `Gradual [Mesedi]`
- **Replace:** `Messedi` (doubled s), `Mesedi [Mesedi]` / `Messedi [Mesedi]` doublings
  *(page_0490, page_0505)*.

### Barekendan — Eve of the Fast (Բարեկենդան)
The threshold feast-day *before* a fast begins (a day of feasting, "good-living"), and by
extension the fast's name. **30×+** as `[Barekendan]`.

- **Canonical:** `Eve of the Fast [Barekendan]` (or, where it names a specific fast,
  `[Barekendan] of the Fast of X`).
- **Replace these wrong renderings:**
  - `Carnival` — interpretive; over-used in Vol II. *(page_0573, page_0596, page_0636)*
  - `Fast-Bidding` *(page_0620)*, `Pre-fast` *(page_0631)*
  - `Day of abstinence` — **semantically wrong** (Barekendan is feasting, not abstinence). *(page_0628)*

### Other recurring anchors (keep as transliterations; do not over-translate)
- `Sharakan` (Շարական) — hymn/canon; keep. **28×**
- `Orhnutyun` (Օրհնութիւն) — the Morning "Blessing" hymn; canonical `Morning Hymn [Orhnutyun]`.
- `Yisnakats` / `Yisnak` — the Nativity-fast (Advent) season term; keep transliteration.
- `Sarok` (Սաղմոս-adjacent canon term, `[sarok'n]`) — keep as `[sarok]`.

---

## Tone codes (the 8-tone / Ձ·Կ system)

The Armenian oktoechos uses **8 tones** = 4 mode-letters **Ա Բ Գ Դ** each in two forms,
**Ձ** (*dzayn*, "voice" / authentic) and **Կ** (*koghm*, "side" / plagal). The code appears
next to nearly every hymn incipit, so its rendering is the highest-volume item in the corpus.

**Keep Gemini's existing bracketed codes as they are** (e.g. `[ak]`, `[dz]`, `[gdz]`, `[bk]`
+ the `Tone N` number). **Do not re-romanize or renumber now** — a consistent scholarly
scheme is deferred until a scholar is consulted. The only edits to make:

**REMOVE these hallucinated glosses** (invented; not in the source):
- Musical keys: `B-flat`, `G-major`, `D-flat` *(page_0602, page_0636)*
- Mode paraphrases: `Plagal Fourth Mode`, `Second Side`, `Fourth Side`,
  `Dzajnakogh-Kogh`, `Kim-Ken / Kamts-Kogh` *(page_0560, page_0570, page_0596, page_0602)*

When one appears, keep the plain `Tone N [code]` and drop the invented phrase, e.g.
`Tone Plagal 2 [bk]` → `Tone 2 [bk]` (keep whatever number Gemini wrote unless the grabar
plainly contradicts it — treat number↔code fixes as ordinary `ERRATA.md` items, not a
systematic renumbering).

---

## How to apply
1. During a Phase-B review batch, normalize each term to its **Canonical** form.
2. Write the normalized text into `book.english.corrected.md` (never the generated
   `book.english.md`).
3. If a normalization is non-obvious or a gloss is uncertain (Hambartsi gloss, tone
   romanization), record the decision in `ERRATA.md` so it is applied consistently.
