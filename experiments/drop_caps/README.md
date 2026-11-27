# Drop-cap lines: the capital shrinks the text the engines read (2026-11-26)

**Question.** On the 372 lines found to open with a drop capital, the two OCR engines
disagree on 13.9% of characters (20.7% on the 206 of them marked with an `initial` op),
against 2.0% on other lines. v4 fell back on 4 such lines in the ceiling run (`p483.003`,
`p508.011`, `p510.054`, `p520.023`, each a heading that opens with a drop capital),
keeping Paddle's reading, because its answer was too far from both readings to accept. Is
the capital the cause? A line crop holds the whole capital, about 5 x-heights tall, and
both recognizers scale every crop to a fixed height, so the text is read smaller than it
would be on its own: at about 60% of its size for the median line, and at a quarter to a
half in the tallest quarter of crops.

**Answer: yes, through the crop's height.** With the capital taken out and the crop cut to
the body text, the engines' disagreement falls from 13.9% of characters to 2.9%, near the
2.0% of other lines (13.1% to 2.9% when the capital is left out of every reading, so both
sides cover the same text). Whitening the capital but keeping the crop as tall leaves it
at 12.9%,
so it is the height the capital adds, not the capital's shape, that the engines stumble on.
On the 4 fallback lines both engines then agree on the body text, apart from one
letter-numeral.

## What was run

`run.py` here, on the 14,709 verified lines (pp.453–643) as of `main` 1914080:

1. **Finding drop caps from the ink**, not from review ops. A line's drop cap is the
   tallest blob in the left quarter of its crop, at least 3 times the text band (median
   blob top to median blob bottom, about the x-height). The capital's other pieces join it:
   blobs off the text band beside it (a Շ's hook and foot, a swash) and a second stroke
   nearly as tall (Ա). A capital touching the first letters is one blob with them; it is
   capital only up to its last column that reaches outside the band.
2. **Four crops of each line:**
   - `orig`: `crops.line_crop`, what the engines read today.
   - `blank`: `orig` with the capital whitened, the crop otherwise unchanged (as tall, as
     wide). This separates the capital's height from its shape.
   - `body`: the capital whitened, its empty columns closed up, the crop cut to the body
     text's rows.
   - `scaled`: `body` with the capital shrunk to the body's capital height and set in
     front, so the line keeps its first letter. This keeps the capital in the reading, so
     it checks that `body` doesn't score better only by leaving out a hard letter.
3. **Both engines on all four**, with the Phase 11 settings: Tesseract `hye-calfa-n`
   (`--psm 13`, whitelist) and `paddle-calfa-tiny` (recognition only).

The `orig` readings match the committed ceiling predictions on 362 (Tesseract) and 364
(Paddle) of the 372 lines. Every mismatch is on one of 23 lines (pp.457–462) whose crop
has changed since the committed predictions were read from it (its box was edited
afterwards); on the other 349 lines both engines read the crop exactly as committed. The
comparison row, "other lines", comes from the committed predictions, not a re-run.

Nothing is typed for this: the measure is how far the two engines' readings are apart
(after the scorer's normalization, edits over Tesseract's length; over the longer reading
it is 13.5% / 2.9% / 3.4% for `orig` / `body` / `scaled`), checked against v4's corrected
text and the few typed lines.

**Like for like.** `blank` and `body` readings lack the capital; `orig` and `scaled` have
it, so they also pay for disagreeing on it. Each comparison is therefore also given with
the capital left out everywhere: the first character dropped from the `orig` and `scaled`
readings (and from v4's text). That is the capital when an engine read it as one letter;
when it read it as none or two, the cut is off by one, which costs at most an edit or two
on that line.

## Results

**Drop caps found: 372.** 206 of the 217 lines with an `initial` op, and 166 lines without
one. All 166 were checked by eye on contact sheets: 163 are real drop caps that the line
boxes took in by themselves (the 2026-11-17 rule that grows a box over the letters it cuts,
`unclip.py`, takes in a capital the box already touches, so review didn't need the Initial
tool for it), and 3 are headings with an enlarged capital (`p486.056`, and Vol II's day
headings `p595.003` and `p599.028`). The 206 with an op weren't checked by eye: review had
already marked each as a drop cap. Most day headings (`6. ԵՐԿՈՒՇԱԲԱԹ.`) have a capital
under 3 bands, among small capitals, and aren't found: a different layout. The 11
`initial`-op lines not found are mostly Հ, whose slanting stroke is shorter than 3 bands.

**The engines' disagreement** (share of lines where the readings differ; edits as a share
of characters):

| lines | crop | lines | characters |
|---|---|--:|--:|
| all 372 | `orig` | 85.8% | 13.9% |
| | `blank` | 83.1% | 12.9% |
| | `body` | 49.2% | **2.9%** |
| | `scaled` | 54.6% | 3.4% |
| 206 with an `initial` op | `orig` | 90.8% | 20.7% |
| | `blank` | 90.3% | 18.9% |
| | `body` | 56.8% | 3.6% |
| | `scaled` | 65.0% | 4.2% |
| 166 without | `orig` | 79.5% | 6.1% |
| | `blank` | 74.1% | 6.0% |
| | `body` | 39.8% | 2.0% |
| | `scaled` | 41.6% | 2.3% |
| other lines (13,755) | `orig` | 34.1% | 2.0% |

Three checks on this:

- **It isn't the capital letter itself.** With the capital left out of every reading
  (characters; lines in brackets):

  | `orig` | `blank` | `body` | `scaled` |
  |--:|--:|--:|--:|
  | 13.1% (80.1%) | 12.9% (83.1%) | 2.9% (49.2%) | 3.1% (52.2%) |

  So disagreeing on the capital adds under a point to `orig`, and the drop to `body` is in
  the body text.
- **It isn't lost text.** The `body` readings are as long as the `orig` ones (26.8 against
  26.6 characters, Tesseract) though they lack the capital.
- **It grows with the crop's height.** By how much taller the `orig` crop is than the
  `body` crop, in quarters of the 372 lines (characters):

  | `orig` height / `body` height | `orig` | `blank` | `body` |
  |---|--:|--:|--:|
  | 1.10–1.61 | 8.4% | 8.4% | 3.6% |
  | 1.61–1.70 | 6.9% | 6.9% | 2.4% |
  | 1.70–1.86 | 6.9% | 6.5% | 2.5% |
  | 1.86–3.93 | 37.1% | 32.8% | 3.1% |

  Every quarter reads better from `body`, but the tallest quarter holds most of the
  disagreement: it is a threshold more than a slope. This is also why the marked lines
  read so much worse than the unmarked ones (20.7% against 6.1%): their capitals are
  larger (median 5.27 bands against 4.87) and their crops taller (1.78 against 1.67 times
  the body).

**Against v4's corrected text** (the 233 drop-cap lines on the 103 corrected pages). As
read: `blank` and `body` against v4's text without its first letter, `orig` and `scaled`
against all of it. Like for like: the capital left out of every reading and of v4.

| crop | Tesseract, as read | Paddle, as read | Tesseract, like for like | Paddle, like for like |
|---|--:|--:|--:|--:|
| `orig` | 11.6% | 4.9% | 11.8% | 4.1% |
| `blank` | 11.3% | 4.9% | 11.3% | 4.9% |
| `body` | 3.9% | 2.5% | 3.9% | 2.5% |
| `scaled` | 4.2% | 2.7% | **3.8%** | **2.4%** |

This favours `orig`: v4 was made from the `orig` readings, and on the 4 fallback lines its
text *is* Paddle's `orig` reading. It also counts some differences no crop could remove:
of the 29 lines where both engines agree on `body` but differ from v4, the 8 looked at
include v4's punctuation and the `՚` its `՚ի` rule adds, along with real misreadings (դ for
գ) and one letter lost with the capital (`p458.063`, `րրորդ` for `րկրորդ`).

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

**The 5 typed drop-cap lines** (edits from the typed line; `blank` and `body` lack the
capital, so they start 1 behind): `scaled` Tesseract is exact on 3 and 1 edit off on 2;
`body` Tesseract, less the missing capital, is exact on 2 and 1 off on 3; `orig`
Tesseract was 6 edits off on `p467.061`.

| line | `orig` T / P | `blank` T / P | `body` T / P | `scaled` T / P |
|---|---|---|---|---|
| `p457.006` | 1 / 1 | 3 / 2 | 2 / 2 | 1 / 1 |
| `p460.020` | 0 / 1 | 1 / 1 | 2 / 1 | 0 / 1 |
| `p467.061` | 6 / 1 | 3 / 3 | 1 / 1 | 1 / 1 |
| `p489.078` | 2 / 2 | 2 / 3 | 2 / 2 | 0 / 1 |
| `p516.072` | 1 / 2 | 2 / 3 | 2 / 2 | 0 / 2 |

## What it means

- The capital is the problem through the crop's height, not its shape: whitened in place
  it still costs nearly as much (`blank`), and with the crop cut to the body these lines
  are about as easy as any other.
- For the body text, `body` and `scaled` are about equal. Like for like, `scaled` is a
  shade closer to v4 (3.8% against 3.9% Tesseract, 2.4% against 2.5% Paddle) and a little
  better on the 5 typed lines, while the engines agree a shade more on `body` (2.9% against
  3.1%). Neither is separated from the other; either crop fixes the body text. (Read as is,
  `scaled` looked worse than `body` against v4, 4.2% against 3.9%, only because it was
  also scored on the capital.)
- The capital reads best from `orig` by Tesseract (103 of 113), and worse once shrunk
  (80), so a design that wants Tesseract's capital reads it from `orig` and the body
  apart.
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
  headings, not drop caps; they stay in the tables. Where the capital touches the next
  letter, the cut can take a letter of body text with it (`p458.063`).

## Reproducing it

```
uv run python experiments/drop_caps/run.py crops                       # needs the page renders
.venv_ml/bin/python experiments/drop_caps/run.py tess
dev/lineseg_survey/.venv-hyocr/bin/python experiments/drop_caps/run.py paddle
uv run python experiments/drop_caps/run.py score
```

Outputs go to `runs/drop_caps/` (git-ignored): the crops, `lines.json` (each line found,
its capital's box and whether it has an `initial` op) and each engine's readings. Both
engines are deterministic: a rerun reproduces the tables, as long as the verified boxes
are the same.
