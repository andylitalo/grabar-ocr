# Phase 11: ceiling of the Calfa engines, and LLM correction (provisional)

Generated 2026-10-09T05:36:18+00:00 by `dev/ocr_eval/ceiling.py`. A line counts as wrong if any character differs after normalization (look-alike punctuation folded, spaces ignored). Rates are weighted back to the whole book from the two strata.

Book: 14388 lines; the OCR engines disagree on 5264 (36.6%). Typed so far: 36 of 300 sampled disagreements, 51 of 200 agreements.

| engine | lines | wrong on disagree | wrong on agree | **error-free lines** | 95% interval | ≈ lines per error | broke (agreed & right → wrong) |
|---|--:|--:|--:|--:|--:|--:|--:|
| `corr-gemini-3.1-pro-v3+rules` | 75 | 4/30 | 1/45 | **93.7%** | 88.5%–98.8% | 16 | 0 |
| `corr-gemini-3.1-pro+rules` | 75 | 6/30 | 0/45 | **92.7%** | 87.8%–97.6% | 14 | 0 |
| `corr-gemini-3.1-pro-v3` | 75 | 7/30 | 7/45 | **81.6%** | 72.5%–89.7% | 5 | 0 |
| `paddle-calfa-tiny+rules` | 87 | 16/36 | 2/51 | **81.3%** | 74.1%–87.8% | 5 | 0 |
| `corr-gemini-3.1-pro` | 75 | 9/30 | 6/45 | **80.6%** | 71.8%–89.5% | 5 | 0 |
| `paddle-calfa-tiny` | 87 | 18/36 | 8/51 | **71.8%** | 62.8%–80.3% | 4 | – |
| `tess-calfa-n+rules` | 87 | 28/36 | 2/51 | **69.1%** | 63.3%–74.9% | 3 | 0 |
| `tess-calfa-n` | 87 | 30/36 | 8/51 | **59.6%** | 52.0%–67.3% | 2 | – |

## Agreed but wrong (both OCR engines made the same mistake)

- `p596~line_077`: ref `՚ի վերդ ես։`, both `ի վերդ ես։`
- `p533~line_028`: ref `՚ի խաղաղութեան. այս նշանաւ սուրբ`, both `ի խաղաղութեան. այս նշանաւ սուրբ`
- `p640~line_080`: ref `՚ի յԵրկրորդ հատորին գտեալ զխորան`, both `ի յԵրկրորդ հատորին գտեալ զխորան`
- `p632~line_061`: ref `Պարսամայ, եւ Ոնոփրիոսի ճըգ-`, both `Պարսամայ, եւ Ոնոփրիոսի ճըդ-`
- `p547~line_063`: ref `յիւրայնոցն։ Ալէ. ՚ի ձայնէն։ Աւետարան`, both `յիւրայնոցն։ Ալէ. ի ձայնէն։ Աւետարան`
- `p491~line_046`: ref `պարտաւորեսցիս։ Մեսե. Աստուած աս-`, both `պարտաւորեսցիս։ Մեսե. Աոտուած աս-`
- `p561~line_061`: ref `սուրբ Կուսին ՚ի յԱննայէ։`, both `սուրբ Կուսին ի յԱննայէ։`
- `p478~line_091`: ref `վ. 28. հաւատովք ՚ի փրկութիւն։ Երգ՝`, both `վ. 28. հաւատովք ի փրկութիւն։ Երգ՝`
