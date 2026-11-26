# Drop-cap lines: the capital shrinks the text the engines read (2026-11-26)

**Question.** On the lines marked as opening with a drop capital, the two OCR engines
disagree on 21% of characters, against 2% on other lines. v4 fell back on 4 such lines in the ceiling run
(`p483.003`, `p508.011`, `p510.054`, `p520.023`), keeping Paddle's reading, because its
answer was too far from both readings to accept. Is the capital the cause? A line crop
holds the whole capital, so it is several times as tall as a line of text, and both
recognizers scale every crop to a fixed height: the text would be read at a fraction of
its size.

**Answer: yes.** With the capital taken out of the crop, the engines' disagreement on the
372 drop-cap lines found falls from 13.9% of characters to 2.9%, near the 2.0% of other
lines. On the 4 fallback lines both engines then agree on the body text, apart from one
letter-numeral.

## What was run

`run.py` here, on the 14,709 verified lines (pp.453–643) as of `main` 1914080:

1. **Finding drop caps from the ink**, not from review ops. A line's drop cap is the
   tallest blob in the left quarter of its crop, at least 3 times the text band (median
   blob top to median blob bottom, about the x-height). The capital's other pieces join it:
   blobs off the text band beside it (a Շ's hook and foot, a swash) and a second stroke
   nearly as tall (Ա). A capital touching the first letters is one blob with them; it is
   capital only up to its last column that reaches outside the band.
2. **Three crops of each line:**
   - `orig`: `crops.line_crop`, what the engines read today.
   - `body`: the capital whitened, its empty columns closed up, the crop cut to the body
     text's rows.
   - `scaled`: `body` with the capital shrunk to the body's capital height and set in
     front, so the line keeps its first letter.
3. **Both engines on all three**, with the Phase 11 settings: Tesseract `hye-calfa-n`
   (`--psm 13`, whitelist) and `paddle-calfa-tiny` (recognition only). The `orig` readings
   match the committed ceiling predictions on 362 (Tesseract) and 364 (Paddle) of the 372
   lines.

Nothing is typed for this: the measure is how far the two engines' readings are apart
(after the scorer's normalization), checked against v4's corrected text and the few typed
lines.

## Results

**Drop caps found: 372.** 206 of the 217 lines with an `initial` op, and 166 lines without
one. All 166 were checked by eye on contact sheets: 163 are real drop caps that the line
boxes took in by themselves (the 2026-11-17 rule that grows a box over the letters it cuts,
`unclip.py`, takes in a capital the box already touches, so review didn't need the Initial
tool for it), and 3 are headings with an enlarged capital (`p486.056`, and Vol II's day
headings `p595.003` and `p599.028`). Most day headings (`6. ԵՐԿՈՒՇԱԲԱԹ.`) have a capital
under 3 bands, among small capitals, and aren't found: a different layout. The 11
`initial`-op lines not found are mostly Հ, whose slanting stroke is shorter than 3 bands.

**The engines' disagreement** (share of lines where the readings differ; edits as a share
of characters):

| lines | crop | lines | characters |
|---|---|--:|--:|
| all 372 | `orig` | 85.8% | 13.9% |
| | `body` | 49.2% | **2.9%** |
| | `scaled` | 54.6% | 3.4% |
| 206 with an `initial` op | `orig` | 90.8% | 20.7% |
| | `body` | 56.8% | 3.6% |
| 166 without | `orig` | 79.5% | 6.1% |
| | `body` | 39.8% | 2.0% |
| other lines (13,755) | `orig` | 34.1% | 2.0% |

The readings didn't get closer by losing text: the `body` readings are as long as the
`orig` ones (26.8 against 26.6 characters, Tesseract) though they lack the capital.

**Against v4's corrected text** (the 233 drop-cap lines on the 103 corrected pages; for
`body`, v4's text without its first letter). v4 was made from the `orig` readings, so this
favours `orig`:

| crop | Tesseract | Paddle |
|---|--:|--:|
| `orig` | 11.6% | 4.9% |
| `body` | **3.9%** | **2.5%** |
| `scaled` | 4.2% | 2.7% |

**The 4 fallback lines**, `body` crop (both engines agree on each, except the
letter-numeral on p510):

| line | `orig`, Paddle | `body`, both engines |
|---|---|---|
| `p483.003` | `(ԱՏԻ ԿՐԿ. Ի ԳԻՇԵՐԻՆ` | `ԱՏԿԻ ԿԻՒՐԱԿԷ. Ի ԳԻՇԵՐԻՆ` |
| `p508.011` | `աթ, տն էսրոյն րիդորիԼու` | `աբաթ. տօն է սրբոյն Գրիգորի Լու-` |
| `p510.054` | `արթ 3 Տօնէ րոյն Գիորի` | `աբաթ գ3. Տօն է սրբոյն Գրիգորի` (Paddle `գձ.`) |
| `p520.023` | `արաթ. ծoն էՇակթինորոյ` | `աբաթ. Տօն է Շողակաթին սրբոյ` |

**The capital itself.** On the 113 found lines with a typed `initial`, the reading's first
letter is the typed capital:

| crop | Tesseract | Paddle |
|---|--:|--:|
| `orig` | **103** | 68 |
| `scaled` | 80 | 86 |

Shrinking the capital helps Paddle read it and hurts Tesseract. `scaled` also picks up an
extra letter now and then from a decorated capital's leftover piece (`Ենրկրորդ`).

**The 5 typed drop-cap lines** (edits from the typed line; `body` lacks the capital, so
it starts 1 behind): `scaled` Tesseract is exact on 2 and 1 edit off on 3; `orig`
Tesseract was 6 edits off on `p467.061`.

| line | `orig` T / P | `body` T / P | `scaled` T / P |
|---|---|---|---|
| `p457.006` | 1 / 1 | 2 / 2 | 1 / 1 |
| `p460.020` | 0 / 1 | 2 / 1 | 0 / 1 |
| `p467.061` | 6 / 1 | 1 / 1 | 1 / 1 |
| `p489.078` | 2 / 2 | 2 / 2 | 0 / 1 |
| `p516.072` | 1 / 2 | 2 / 2 | 0 / 2 |

## What it means

- The capital is the problem, through the crop's height, not the type: read at their own
  size, these lines are about as easy as any other.
- The body text reads best from `body`, and the capital best from `orig` by Tesseract, so
  the two are best read apart.
- Drop-cap lines still disagree a little more than other lines (2.9% against 2.0% of
  characters, 49% against 34% of lines). Leftover pieces of decorated capitals account for
  some of it.
- Marked drop caps undercount them: 166 of the 372 have no `initial` op.

## Limits

- The measure is mostly the engines' agreement, not accuracy: only 5 drop-cap lines are
  typed. Agreement tracks accuracy here (the comparison with v4 and the typed lines move
  the same way), but a drop-cap stratum of typed lines is what will score it.
- The detector was tuned by eye on contact sheets of these lines, so its 372 aren't an
  independent count. Drop caps under 3 bands (most Հ) are missed, and 3 of the 372 are
  headings, not drop caps; they stay in the tables.

## Reproducing it

```
uv run python experiments/drop_caps/run.py crops                       # needs the page renders
.venv_ml/bin/python experiments/drop_caps/run.py tess
dev/lineseg_survey/.venv-hyocr/bin/python experiments/drop_caps/run.py paddle
uv run python experiments/drop_caps/run.py score
```

Outputs go to `runs/drop_caps/` (git-ignored): the crops, `lines.json` (each line found,
its capital's box and whether it has an `initial` op) and each engine's readings. Both
engines are deterministic, so a rerun reproduces the tables.
