# Phase 1 Results — Baseline OCR (Off-the-Shelf TrOCR)

**Date completed:** 2026-04-13
**Status:** Complete

---

## Summary

| Model | CER | Notes |
|-------|-----|-------|
| `trocr-base-printed` | **93.4%** | Best performer; Latin-like output |
| `trocr-large-printed` | 97.9% | Worse than base; collapses to `***` more often; receipt-vocabulary hallucinations |
| `trocr-base-handwritten` | 138.7% | Worst; outputs fluent-sounding English nonsense; CER > 100% due to long insertions |

**Decision tree outcome:** CER > 70% across all variants → fine-tuning is essential and expected to yield dramatic improvement.

---

## Per-Line Output: `trocr-base-printed` (best variant)

| File | Prediction | Ground Truth |
|------|-----------|--------------|
| line_001.png | `ALUM_GKG WTOPHLING QKULOW.` | Ուսուցից անօրինաց զճանա- |
| line_002.png | `WWPLY,PA, LL_WDYWP2NP` | պարհս քո, եւ ամպարիշտք |
| line_003.png | `UN PKA TWPAYHL:` | առ քեզ դարձցին։ |
| line_004.png | `OPPLY AND JUPBLE, MU.` | Փրկեա զիս յարենէ, աս- |
| line_005.png | `UNLAB, WOWNLWS APPLAC.` | տուած, աստուած փրկու- |
| line_006.png | `[BILL LIFY. JLOWGET ITAML` | թեան իմոյ. ցնծասցէ լեզու |
| line_007.png | `[L]` | իմ յարդարութեան քում։ |
| line_008.png | `SUP, LPB, 420BALAN JL PW,` | Տէր, եթէ զշրթունս իմ բա- |
| line_009.png | `WWW, PERMAN BE EPQERAGE` | նաս, բերան իմ երգեսցէ |
| line_010.png | `4094LPHAN PR:` | զօրհնութիւնս քո։ |
| line_011.png | `@4 LMLKGKW_EP MYWW.` | Թէ կամեցեալ էիր պատա- |
| line_012.png | `PAINT SUMM_GULFWP, PEG` | րագս մատուցանեմք, բայց |
| line_013.png | `TAL QTY MOZULTAN BULY MY` | դու ընդ ողջակէզս իսկ ոչ |
| line_014.png | `AMXKYWR:` | հաճեցար։ |
| line_015.png | `QUMWPUN WWWMLSAJ 4MM` | Պատարագ աստուծոյ՝ հոգի |
| line_016.png | `LAMPLY, COMPA WWAPP KL` | խոնարհ, զսիրտ սուրբ եւ |
| line_017.png | `45MM HMLUPS WUMMLMB MY` | զհոգի խոնարհ աստուած ոչ |
| line_018.png | `WW.COM.COM.` | արհամարհէ։ |
| line_019.png | `PAY MON, MEP, LUMP` | Բարի արա, տէր, կամօք |
| line_020.png | `PAULP W/ML, LL ZBLANGHL` | քովք սիոնի, եւ շինեսցին |
| line_021.png | `WWW.WW.PL.L.PML.COM/KLK` | պարիսպքն երուսաղեմի։ |
| line_022.png | `BAYLB UNI' 4MXBUGHA PLOT RAUL.` | Յայնժամ հաճեսցիս ընդ պա- |
| line_023.png | `WWWWW.` | տարագս արդարութեան, |
| line_024.png | `JMPEWP MCHANKY WWWW.` | յորժամ ուխտից պատա- |
| line_025.png | `PAINTA SANDGETA 'B UERUAL.PR` | րագս հանցեն ՚ի սեղան քո |
| line_026.png | `WWWWW:` | զուարակս։ |
| line_027.png | `PUMP COP. U.JDF FL IDZIM` | Փառք հօր. Այժմ եւ միշտ։ |
| line_028.png | `IT RMMARY` *(section marker — excluded)* | — |
| line_029.png | `***` *(section marker — excluded)* | — |
| line_030.png | `GPA HIPAPPH FWDML WLMLPLPU` | Երգ երրորդի ժամու աւուրն |
| line_031.png | `***` | զկնի Ողորմեաին։ |
| line_032.png | `ORCHASE SUPPA SOUP WITHIN.` | Օրհնեմք ըզքեզ հայր անըս- |
| line_033.png | `4FACE +PG FULL 'H JULATQG,` | կիզբն էից էակ ՚ի յանգոյից, |
| line_034.png | `PAUDSLP BERLOP UPLIP 'R 4ML` | բարձր ձեռօք նիւթ ՚ի հո- |
| line_035.png | `"MYL. ...PLEAPEP ADJY 'H UJAW.` | ղոյ և ստեղծեր մարդ ՚ի պատ- |
| line_036.png | `4KP PRI. 4[ML POPL NUMPG PAN.` | կեր քո. գլուխըն ոտից խո- |

---

## Failure Mode Analysis

| Pattern | Observed | Interpretation |
|---------|----------|----------------|
| All-Latin/uppercase output | All lines, all models | Encoder maps Bolorgir glyphs to visually similar Latin shapes; no Armenian Unicode in decoder vocabulary |
| `WWW...` repeated sequences | Lines 009, 018, 020–021, 023, 026 | Repeated similar glyphs (Armenian letters with shared strokes) collapse to repeated tokens |
| `***` collapses | Lines 029, 031 (base); 011, 013, 020 (large) | Decoder gives up on visually unusual patterns; more common in `trocr-large` |
| `՚ի` → `'H` or `'B` | Lines 025, 033–035 | Apostrophe-like elision glyph partially recognized across all models |
| Receipt vocabulary (large model) | Lines 025–026: `PURCHASE AND RETURN WITH RECEIPT`, `TOTAL:` | `trocr-large-printed` appears heavily trained on receipt/form data |
| Fluent English nonsense (handwritten) | All lines | Handwritten model generates plausible-looking English sentences; Bolorgir calligraphic strokes match handwriting features |
| Section markers hallucinated | Both markers, all models | Model always generates *something*; `base-printed`: `IT RMMARY` / `***`; `large-printed`: `-` / `- - - -`; `base-handwritten`: `0 0 0 0...` sequences |
| CER > 100% (handwritten) | 138.7% | Long insertion hallucinations exceed reference length — decoder generates far more characters than exist |

---

## Key Conclusions

1. **Best base model: `trocr-base-printed`** (93.4% CER). Larger or handwriting-tuned variants perform worse on Bolorgir.
2. **No Armenian Unicode produced by any model.** The decoder vocabulary contains no Armenian code points — every output is Latin. Fine-tuning must teach the model an entirely new output character set.
3. **Visual encoder does capture some structure.** Word count and rough token boundaries often match (e.g. 3-word lines produce 3-token outputs). The encoder is doing useful work; only the decoder needs retraining.
4. **Section markers are always hallucinated.** The model has no "no text" concept — relevant for pipeline design (a confidence threshold or post-processing step will be needed).
5. **`՚ի` elision glyph is partially recognized** across models, suggesting the ViT encoder has latent sensitivity to some Bolorgir shapes.

---

## Recommended Next Step

Proceed to **Phase 2** (server bootstrap) + **Phase 3** (fine-tuning on Phase 0 golden data). The 93.4% baseline gives us a clear floor; even a small fine-tuning run on 34 lines should demonstrate measurable improvement toward the target.
