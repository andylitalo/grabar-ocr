# Տօնացոյց (Tōnatsooyts) — Source Typos & Errata

A registry of **typographical errors in the printed Տօնացոյց** (*Tōnatsooyts*, the Armenian
Church Calendar/Typikon) discovered while digitizing and validating this corpus. The
digitization is **faithful** — the transcription in `corpus/` reproduces what the page
actually prints, typos included — so this file records where the *printed source itself* is
wrong, with the evidence, so downstream consumers (e.g. the `armenian-lectionary` engine)
can correct it deliberately rather than silently.

Errata are grouped into two classes:

- **Consequential** — the typo would change a *reading or scripture citation*. A downstream
  consumer should ship the corrected value; the fix is testable against external ground
  truth (e.g. sacredtradition.am).
- **Inconsequential** — an orthographic slip in *quoted liturgical text* (a hymn incipit, a
  psalm tag, a spelling) with no effect on any reading or citation. Recorded for
  transcription fidelity only; nothing downstream depends on them.

This is distinct from a *versification-convention* difference (the same pericope numbered on
a different scale), which is not an error; those are handled by the consuming engine's
`source_corrections` registry, not here.

---

## Consequential typos (affect a reading or citation)

### 1. Proverbs 8 endpoint — Eve of the Presentation of the Lord (Feb 13), First Volume p. 462

*Location:* `corpus/pages/page_0462.md:95` — «Առակ. Ը. 22. Տէր ստացաւ զիս. **վ. 24.** որ
զճանապարհս իմ պահիցէ։»

| | |
|---|---|
| **Source prints** | `Առակ. Ը. 22 … վ. 24` — "Proverbs 8:22 … to verse 24", endpoint quoted «որ զճանապարհս իմ պահիցէ» |
| **Correct** | **`Proverbs 8:22-34`** |
| **Classification** | Transposed digit — printed `24`, should be `34` |

**Why it is a typo, not a versification variant.** The Տօնացոյց cites the reading's endpoint
by quoting its closing words: «...որ զճանապարհս իմ **պահիցէ**» ("...who keeps my ways"). In
the Grabar (Classical Armenian) Proverbs, that phrase is verbatim the close of **verse 34**,
not verse 24:

- **8:24** — «Նախ քան զանդունդս գործել, նախ քան զբղխել աղբերաց ջրոց» — *"When there were no
  depths, I was brought forth; when there were no fountains abounding with water"* — has
  nothing to do with "keeping [my] ways".
- **8:32** — «Արդ, որդեակ, լուր ինձ. եւ երանելի են՝ որ զճանապարհս իմ **պահեսցեն**» — *"Now
  therefore hearken unto me... blessed are they that keep my ways"* — near-identical, but
  uses the **plural** «պահեսցեն».
- **8:34** — «Երանելի է այր որ լուիցէ ինձ, եւ մարդ որ զճանապարհս իմ **պահիցէ**, տքնիցի առ
  դրունս իմ հանապազ...» — *"Blessed is the man that heareth me... that keepeth my ways,
  watching daily at my gates..."* — the **singular** «պահիցէ» matches the Տօնացոյց's quoted
  endpoint **exactly**.

The singular verb form «պահիցէ» disambiguates against the 8:32 twin and fixes the endpoint at
**8:34**. So the pericope is `8:22-34`; the printed verse number "24" is a `3`→`2`
transposition.

**Independent cross-check.** sacredtradition.am renders this reading `Proverbs 8:22-34`
unanimously — **23/23** Feb-13 eve years and **26/26** Feb-14 (Presentation feast) years in
the `armenian-lectionary` reference cache. The Grabar Proverbs 8 source consulted:
<https://arak29.org/bible/book/tProv_8.htm>.

**Downstream handling.** The `armenian-lectionary` engine ships the corrected
`Proverbs 8.22-34` (in `_PRESENTATION_EVE_BLOCK`), which the cache already matches, so no
override is required there.

---

## Inconsequential typos (orthographic; no effect on readings or citations)

### i1. `երեւեցաւ` spelled with a doubled ե — First Volume p. 462

*Location:* `corpus/pages/page_0462.md:82` — «Տէր աստուած մեր **երեեւեցաւ**։»

| | |
|---|---|
| **Source prints** | «երեեւեցաւ» (doubled initial ե) |
| **Correct** | «երեւեցաւ» — *"[he] appeared"* (aorist of երեւիմ) |
| **Classification** | Doubled letter — spurious extra `ե` |

Occurs in the **Mesedi of the Coming** (Feb-13 eve of the Presentation), quoting Ps 118:26-27:
«Օրհնեալ եկեալ անուամբ տեառն. Տէր աստուած մեր երեւեցաւ» — *"Blessed is he that cometh in the
name of the Lord; the Lord our God hath appeared unto us."* Pure spelling slip in a hymn
incipit; it names no reading and changes no citation. Recorded for transcription fidelity
only.
