# Phase 11: ceiling of the Calfa engines, and LLM correction (provisional)

Generated 2026-10-09T14:37:43+00:00 by `dev/ocr_eval/ceiling.py`. A line counts as wrong if any character differs after normalization (look-alike punctuation folded, spaces ignored). Rates are weighted back to the whole book from the two strata.

Book: 14388 lines; the OCR engines disagree on 5264 (36.6%). Typed so far: 58 of 300 sampled disagreements, 102 of 200 agreements.

| engine | lines | wrong on disagree | wrong on agree | **error-free lines** | 95% interval | ≈ lines per error | broke (agreed & right → wrong) |
|---|--:|--:|--:|--:|--:|--:|--:|
| `corr-gemini-3.1-pro-v4+rules` | 54 | 1/20 | 3/34 | **92.6%** | 85.2%–98.2% | 13 | 0 |
| `corr-gemini-3.1-pro-v3+rules` | 117 | 5/50 | 4/67 | **92.6%** | 87.7%–96.9% | 13 | 0 |
| `corr-gemini-3.1-pro+rules` | 115 | 8/49 | 4/66 | **90.2%** | 84.5%–95.1% | 10 | 1 |
| `corr-gemini-3.1-pro-v4` | 54 | 3/20 | 6/34 | **83.3%** | 74.0%–92.6% | 6 | 0 |
| `corr-gemini-3.1-pro-v3` | 117 | 10/50 | 10/67 | **83.2%** | 76.5%–89.6% | 6 | 0 |
| `corr-gemini-3.1-pro` | 115 | 12/49 | 10/66 | **81.4%** | 74.4%–88.3% | 5 | 1 |
| `paddle-calfa-tiny+rules` | 160 | 25/58 | 8/102 | **79.3%** | 73.6%–84.9% | 5 | 0 |
| `paddle-calfa-tiny` | 160 | 28/58 | 19/102 | **70.5%** | 64.3%–76.8% | 3 | – |
| `tess-calfa-n+rules` | 160 | 44/58 | 8/102 | **67.3%** | 62.3%–72.3% | 3 | 0 |
| `tess-calfa-n` | 160 | 47/58 | 19/102 | **58.5%** | 52.3%–64.8% | 2 | – |

## Agreed but wrong (both OCR engines made the same mistake)

- `p596~line_077`: ref `՚ի վերդ ես։`, both `ի վերդ ես։`
- `p533~line_028`: ref `՚ի խաղաղութեան. այս նշանաւ սուրբ`, both `ի խաղաղութեան. այս նշանաւ սուրբ`
- `p640~line_080`: ref `՚ի յԵրկրորդ հատորին գտեալ զխորան`, both `ի յԵրկրորդ հատորին գտեալ զխորան`
- `p632~line_061`: ref `Պարսամայ, եւ Ոնոփրիոսի ճըգ-`, both `Պարսամայ, եւ Ոնոփրիոսի ճըդ-`
- `p547~line_063`: ref `յիւրայնոցն։ Ալէ. ՚ի ձայնէն։ Աւետարան`, both `յիւրայնոցն։ Ալէ. ի ձայնէն։ Աւետարան`
- `p491~line_046`: ref `պարտաւորեսցիս։ Մեսե. Աստուած աս-`, both `պարտաւորեսցիս։ Մեսե. Աոտուած աս-`
- `p561~line_061`: ref `սուրբ Կուսին ՚ի յԱննայէ։`, both `սուրբ Կուսին ի յԱննայէ։`
- `p478~line_091`: ref `վ. 28. հաւատովք ՚ի փրկութիւն։ Երգ՝`, both `վ. 28. հաւատովք ի փրկութիւն։ Երգ՝`
- `p494~line_027`: ref `Համբ. բձ. Կանխեցին. Զյարութիւն. և`, both `Համբ. բկ. Կանխեցին. Զյարութիւն. և`
- `p543~line_013`: ref `և միջոցդ իբրու անշարժք, սակայն ոմանք տօնք շար-`, both `և միջոցդ իբրու անշարժք. սակայն ոմանք տօնք շար-`
- `p638~line_028`: ref `աձ. Ըզքեզ արդար եւ ուղիղ դա-`, both `այ. Ըզքեզ արդար եւ ուղիղ դա-`
- `p457.006`: ref `Եւ առաւօտու օրհնութիւն. դկ. Խոր-`, both `Եւ առաւօտու օրհնութիւն. գկ. Խոր-`
- `p475~line_020`: ref `որպէս ՚ի վերոյ։`, both `որպէս ի վերոյ։`
- `p504~line_061`: ref `նման հօր եւ. զերկուսն ՚ի միասին ասա։ Ա-`, both `նման հօր եւ. զերկուսն ի միասին ասա։ Ա-`
- `p505~line_015`: ref `իւր սարօքն։ Ալէ. սաղ. Առաքես զոգի`, both `իւր սարօքն։ Ալէ. սաղ. Առաքես զողի`
- `p538~line_036`: ref `կեցցէ ՚ի նոսին։ Ալէ. ՚ի ձայնէն։ Աւե-`, both `կեցցէ ի նոսին։ Ալէ. ի ձայնէն։ Աւե-`
- `p623~line_041`: ref `Ծննդեան Ս. Կուսին ՚ի յԱննայէ։`, both `Ծննդեան Ս. Կուսին ի յԱննայէ։`
- `p634~line_012`: ref `Աստուածածնի ՚ի յԱննայէ։`, both `Աստուածածնի ի յԱննայէ։`
- `p604~line_023`: ref `հարցիցն ասա տես։`, both `հարցիցն աստ տես։`
