# Full pipeline test — page_0487 (automated, no human reference yet)
Automated path: PDF → deskew → auto column-detect → auto line-slice → TrOCR → LLM correct.
Compare each artifact below against the human version you produce.
## Step 1 — column detection (deskew + projection gutter)
- deskew angle applied: **0.30°**, detector **confident**
- column 1 box (full-res px): x[145–967] y[269–2956]
- column 2 box (full-res px): x[967–1833] y[263–2953]
- crops: `data/columns/page_0487_auto_column_{1,2}.png`

## Step 2 — line slicing
- column_1: **50** lines · column_2: **48** lines (total **98**)
- crops: `data/lines/page_0487_auto/column_{1,2}/line_NNN.png`

## Step 3 — OCR (TrOCR scale_500, beam-4)
- raw text: `data/predictions/scale_500/page_0487_auto/ocr_text.txt`

## Step 4 — LLM correction (gemini-3.1-pro, minimal-edit)
- final text: `data/predictions/scale_500_llm_gemini_minimal-edit/page_0487_auto/digitized.txt`
- lines changed: **22/98** · cost ≈ $0.014/page

### Lines the LLM corrected (OCR → corrected)

**column_1/line_002**  
`OCR ` եթէ յայլ աւուրսն՝ զԱրարչական երդն  
`LLM ` եթէ յայլ աւուրսն՝ զԱրարչական երգն

**column_1/line_003**  
`OCR ` ասա. եւ զկնի՝ Մածկեալ խորհուրդն ծա  
`LLM ` ասա. եւ զկնի՝ Ծածկեալ խորհուրդն ծա

**column_1/line_004**  
`OCR ` Ճաշու մամամուտ, Աստուածածին ան-  
`LLM ` Ճաշու ժամամուտ, Աստուածածին ան-

**column_1/line_016**  
`OCR ` զսորհուրդն անճան քաղեա իւր սա-  
`LLM ` զխորհուրդն անճառ քաղեա իւր սա-

**column_1/line_019**  
`OCR ` ծածինն։ Սղօթք, Ընկալ տէր։ Եւ ապա  
`LLM ` ծածինն։ Աղօթք, Ընկալ տէր։ Եւ ապա

**column_1/line_021**  
`OCR ` ւուր Ղաղարու շաբաթին, կամ յաւագ  
`LLM ` ւուր Ղազարու շաբաթին, կամ յաւագ

**column_1/line_026**  
`OCR ` դերձ իւր սարօքն քաղեա. զաւուր զիրք  
`LLM ` դերձ իւր սարօքն քաղեա. զաւուր գիրք

**column_1/line_028**  
`OCR ` իւ զհոգւոցն ասա։ Եւ ապա սկսեա՝ զտօ  
`LLM ` եւ զհոգւոցն ասա։ Եւ ապա սկսեա՝ զտօ

**column_1/line_040**  
`OCR ` Իսկ ՚ի հաշուն եւ յերեկոյին սաղմոս�  
`LLM ` Իսկ ՚ի ճաշուն եւ յերեկոյին սաղմոս�

**column_1/line_048**  
`OCR ` Հաիկ։ Եիշերին հսկուն է։ Կանո-  
`LLM ` Հաիկ։ Գիշերին հսկուն է։ Կանո-

**column_1/line_049**  
`OCR ` նագլուի, Օրհնեա անձն իմ. սիոխ, Օրհ-  
`LLM ` նագլուխ, Օրհնեա անձն իմ. սիոխ, Օրհ-

**column_2/line_005**  
`OCR ` Յոյց մեզ աէր. փոխ, Հաճեցար տէր ընդ  
`LLM ` Ցոյց մեզ տէր. փոխ, Հաճեցար տէր ընդ

**column_2/line_009**  
`OCR ` մէն նոցա գնայր։ նկնի՝ յորաստեղծեա  
`LLM ` մէջ նոցա գնայր։ զկնի՝ յորաստեղծեա

**column_2/line_010**  
`OCR ` Քարոզ, Խնղրեսցուք. Կեցո։ Աղօթք,  
`LLM ` Քարոզ, Խնդրեսցուք. Կեցո։ Աղօթք,

**column_2/line_013**  
`OCR ` յամին կիռրակեի և ՚ի շաբաջի՝ Քրիստ�  
`LLM ` յամին կիռրակեի և ՚ի շաբաթի՝ Քրիստ�

**column_2/line_016**  
`OCR ` վուեսցէ. Տեառէ է երկիր. Առ քեզ տէր  
`LLM ` վուեսցէ. Տեառն է երկիր. Առ քեզ տէր

**column_2/line_020**  
`OCR ` բաղում վարդապեմք. վ. 12. Չուր քաղցր  
`LLM ` բազում վարդապետք. վ. 12. Ջուր քաղցր

**column_2/line_022**  
`OCR ` ղէմ։ Աւետարան Յսվհ. Ա. 1. Ի սկզբանէ  
`LLM ` ղէմ։ Աւետարան Յովհ. Ա. 1. Ի սկզբանէ

**column_2/line_031**  
`OCR ` սաղ. Դ. Ԇշանեցաւ. տոխ, Ի կարդալ։  
`LLM ` սաղ. Դ. Ԇշանեցաւ. փոխ, Ի կարդալ։

**column_2/line_034**  
`OCR ` Եւ տեանաղրեսցեն զանղաստանն։ Քա-  
`LLM ` Եւ տեանաղրեսցեն զանդաստանն։ Քա-

**column_2/line_038**  
`OCR ` աուծոց. տոխ, Յելիցն արեգական։ Հմբ.  
`LLM ` աուծոց. փոխ, Յելիցն արեգական։ Հմբ.

**column_2/line_048**  
`OCR ` Ճաշու սաղ. ԻԷ. Դատ տրա ինձ. Տէր  
`LLM ` Ճաշու սաղ. ԻԷ. Դատ արա ինձ. Տէր
