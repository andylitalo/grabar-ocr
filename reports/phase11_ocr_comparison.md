# Phase 11: OCR engine comparison (provisional)

Generated 2026-10-05T14:42:36+00:00 by `dev/ocr_eval/score.py`. Plan: `docs/phase_11_ocr_comparison.md`.

**12 lines, 382 characters**, scored identically for every engine (of 12 transcribed). CER is pooled over lines; look-alike punctuation is folded. Intervals are 95% bootstrap over lines: where they overlap, the ranking isn't settled.

| engine | CER | 95% interval | spaces ignored | raw (no folding) |
|---|--:|--:|--:|--:|
| `paddle-calfa-tiny` | **0.0%** | 0.0%–0.0% | 0.0% | 0.0% |
| `tess-calfa-n` | **0.0%** | 0.0%–0.0% | 0.0% | 0.0% |
| `tess-grabar` | **0.5%** | 0.0%–1.2% | 0.6% | 0.5% |
| `gemini-pro` | **6.3%** | 2.9%–10.2% | 0.9% | 8.9% |
| `gemini-flash` | **7.1%** | 4.2%–10.5% | 0.9% | 10.5% |
| `trocr-ft` | **8.6%** | 2.2%–21.6% | 7.6% | 8.6% |

## Breakdown

| engine | vol1-body (n=12) | without ՟ (n=12) |
|---|--:|--:|
| `paddle-calfa-tiny` | 0.0% | 0.0% |
| `tess-calfa-n` | 0.0% | 0.0% |
| `tess-grabar` | 0.5% | 0.5% |
| `gemini-pro` | 6.3% | 6.3% |
| `gemini-flash` | 7.1% | 7.1% |
| `trocr-ft` | 8.6% | 8.6% |

## Noise floor

No blind rechecks yet.

## Worst lines per engine

**`paddle-calfa-tiny`**

- no errors

**`tess-calfa-n`**

- no errors

**`tess-grabar`**

- `p458.056` (vol1-body)
  - ref: Օրհնութիւնն ասա։ Իսկ զկնի Հայր գը-
  - hyp: Օրհնութիւնն ասա։ Իսկ զկնի հայր գը-
- `p462.058` (vol1-body)
  - ref: զԱպրեցո։ Լոյս զուարթ։ Մեսեդի Գալըս-
  - hyp: զԱպրեցո։ Լոյս զուարթ։ Մեսեդի Գալրս-

**`gemini-pro`**

- `p458.086` (vol1-body)
  - ref: Եբր. Ա. 1. Բազում մասամբք. վ. 12.
  - hyp: Եբր . Ա . 1 . Բազում մասամբք . Վ . 12 .
- `p457.062` (vol1-body)
  - ref: Բ. 11. Քանզի երեւեցաւ. վ. 15. զի
  - hyp: Բ . 11 . Քանզի երեւեցաւ . վ . 15 . զի
- `p462.079` (vol1-body)
  - ref: օրէնքն դաստիարակք. վ. 29. ըստ աւե-
  - hyp: օրէնքն դաստիարակք . վ . 29 . ըստ աւե֊

**`gemini-flash`**

- `p458.086` (vol1-body)
  - ref: Եբր. Ա. 1. Բազում մասամբք. վ. 12.
  - hyp: եբր . Ա . 1 . Բազում մասամբք . վ . 12 .
- `p459.028` (vol1-body)
  - ref: նիւքս այսոքիւք։ Ալէ. Եհան զիս. Աւե-
  - hyp: նիւքս այսոքիւք ։ Ալէ ․ եհան զիս ․ Աւե֊
- `p462.079` (vol1-body)
  - ref: օրէնքն դաստիարակք. վ. 29. ըստ աւե-
  - hyp: օրէնքն դաստիարակք ․ վ ․ 29 ․ ըստ աւե֊

**`trocr-ft`**

- `p453.006` (vol1-body)
  - ref: ՍԿԶԲՆԱՒՈՐԵԱԼ
  - hyp: Սէ Ձ բչ ս Լ Լ ո Ո է սւ
- `p462.058` (vol1-body)
  - ref: զԱպրեցո։ Լոյս զուարթ։ Մեսեդի Գալըս-
  - hyp: զԱպրեցո։ Ղոյս զուարթ։ Մեսեդի Գալր�
- `p458.056` (vol1-body)
  - ref: Օրհնութիւնն ասա։ Իսկ զկնի Հայր գը-
  - hyp: Օրհնութիւնն ասա։ Իսկ զկնի հայր գշ-

