# Phase 5 — LLM correction summary

_Updated 2026-06-16. Gate: page_0400_human ≤0.3%; clear net reduction on page_0251_human/page_0499_human; over-correction ≈ 0. **gemini-3.1-pro rows use the REFINED (v2) prompt** (tightened notation/punctuation/case preservation → eliminated over-correction); opus/sonnet/gpt-5.5 rows use the original (v1) prompt. Sonnet 4.6 truncates under adaptive thinking (parse_ok False). gpt-5.5 uses reasoning_effort=low. OpenAI/Gemini $ are ESTIMATES._

| page | model | mode | n | CER base | CER corr | Δ pts | rel | worse | broke✓ | changed | parse_ok | $/page | $/1k |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|--:|--:|
| page_0251_human | claude-opus-4-8 | minimal-edit | 58 | 0.32% | 0.08% | +0.24 | 75% | 1 | 1 | 3 | True | $0.0254 | $25.39 |
| page_0251_human | gemini-3.1-pro | minimal-edit | 58 | 0.32% | 0.32% | +0.00 | 0% | 0 | 0 | 1 | True | $0.0035 | $3.50 |
| page_0251_human | gpt-5.5 | minimal-edit | 58 | 0.32% | 0.56% | -0.24 | -75% | 3 | 3 | 5 | True | $0.0122 | $12.22 |
| page_0251_human | claude-opus-4-8 | rewrite | 58 | 0.32% | 0.08% | +0.24 | 75% | 1 | 1 | 3 | True | $0.0469 | $46.88 |
| page_0251_human | claude-sonnet-4-6 | rewrite | 58 | 0.32% | 0.32% | +0.00 | 0% | 0 | 0 | 0 | False | $0.1248 | $124.78 |
| page_0251_human | gemini-3.1-pro | rewrite | 58 | 0.32% | 0.08% | +0.24 | 75% | 0 | 0 | 2 | True | $0.0165 | $16.51 |
| page_0251_human | gpt-5.5 | rewrite | 58 | 0.32% | 0.08% | +0.24 | 75% | 1 | 1 | 3 | True | $0.0217 | $21.73 |
| page_0400_human | claude-opus-4-8 | minimal-edit | 71 | 1.02% | 0.41% | +0.61 | 60% | 1 | 0 | 10 | True | $0.0611 | $61.09 |
| page_0400_human | claude-sonnet-4-6 | minimal-edit | 71 | 1.02% | 1.02% | +0.00 | 0% | 0 | 0 | 0 | False | $0.2454 | $245.44 |
| page_0400_human | gemini-3.1-pro | minimal-edit | 71 | 1.02% | 0.41% | +0.61 | 60% | 0 | 0 | 9 | True | $0.0065 | $6.51 |
| page_0400_human | gpt-5.5 | minimal-edit | 71 | 1.02% | 0.41% | +0.61 | 60% | 1 | 1 | 10 | True | $0.0126 | $12.58 |
| page_0400_human | claude-opus-4-8 | rewrite | 71 | 1.02% | 0.27% | +0.75 | 73% | 1 | 1 | 11 | True | $0.1541 | $154.10 |
| page_0400_human | claude-sonnet-4-6 | rewrite | 71 | 1.02% | 1.02% | +0.00 | 0% | 0 | 0 | 0 | False | $0.2454 | $245.36 |
| page_0400_human | gemini-3.1-pro | rewrite | 71 | 1.02% | 0.34% | +0.68 | 67% | 0 | 0 | 9 | True | $0.0190 | $19.02 |
| page_0400_human | gpt-5.5 | rewrite | 71 | 1.02% | 0.41% | +0.61 | 60% | 2 | 2 | 11 | True | $0.0238 | $23.75 |
| page_0499_human | claude-opus-4-8 | minimal-edit | 92 | 0.38% | 0.28% | +0.10 | 27% | 2 | 2 | 7 | True | $0.0753 | $75.25 |
| page_0499_human | gemini-3.1-pro | minimal-edit | 92 | 0.38% | 0.24% | +0.14 | 36% | 0 | 0 | 4 | True | $0.0069 | $6.93 |
| page_0499_human | gpt-5.5 | minimal-edit | 92 | 0.38% | 0.55% | -0.17 | -45% | 6 | 6 | 10 | True | $0.0194 | $19.41 |
| page_0499_human | claude-opus-4-8 | rewrite | 92 | 0.38% | 0.48% | -0.10 | -27% | 8 | 8 | 13 | True | $0.2282 | $228.19 |
| page_0499_human | claude-sonnet-4-6 | rewrite | 92 | 0.38% | 0.38% | +0.00 | 0% | 0 | 0 | 0 | False | $0.1299 | $129.88 |
| page_0499_human | gemini-3.1-pro | rewrite | 92 | 0.38% | 0.24% | +0.14 | 36% | 0 | 0 | 4 | True | $0.0357 | $35.73 |
| page_0499_human | gpt-5.5 | rewrite | 92 | 0.38% | 1.82% | -1.45 | -382% | 16 | 15 | 20 | True | $0.0362 | $36.17 |
