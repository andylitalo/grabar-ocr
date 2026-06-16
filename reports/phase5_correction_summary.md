# Phase 5 — LLM correction summary

_Updated 2026-06-16 · baseline vs corrected CER, over-correction, and per-page cost. Gate: page_0400 ≤0.3%; clear net reduction on page_0251/page_0499; over-correction ≈ 0. Sonnet 4.6 over-thinks to the token cap under adaptive thinking and never emits the answer (parse_ok False → baseline). gpt-5.5 run with reasoning_effort=low (default reasoning hung > the SDK timeout); OpenAI/Gemini $ are ESTIMATES._

| page | model | mode | n | CER base | CER corr | Δ pts | rel | worse | broke✓ | changed | parse_ok | $/page | $/1k |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|--:|--:|
| page_0251 | claude-opus-4-8 | minimal-edit | 58 | 0.32% | 0.08% | +0.24 | 75% | 1 | 1 | 3 | True | $0.0254 | $25.39 |
| page_0251 | gemini-3.1-pro | minimal-edit | 58 | 0.32% | 0.08% | +0.24 | 75% | 1 | 1 | 3 | True | $0.0039 | $3.89 |
| page_0251 | gpt-5.5 | minimal-edit | 58 | 0.32% | 0.56% | -0.24 | -75% | 3 | 3 | 5 | True | $0.0122 | $12.22 |
| page_0251 | claude-opus-4-8 | rewrite | 58 | 0.32% | 0.08% | +0.24 | 75% | 1 | 1 | 3 | True | $0.0469 | $46.88 |
| page_0251 | claude-sonnet-4-6 | rewrite | 58 | 0.32% | 0.32% | +0.00 | 0% | 0 | 0 | 0 | False | $0.1248 | $124.78 |
| page_0251 | gemini-3.1-pro | rewrite | 58 | 0.32% | 0.08% | +0.24 | 75% | 1 | 1 | 3 | True | $0.0161 | $16.10 |
| page_0251 | gpt-5.5 | rewrite | 58 | 0.32% | 0.08% | +0.24 | 75% | 1 | 1 | 3 | True | $0.0217 | $21.73 |
| page_0400 | claude-opus-4-8 | minimal-edit | 71 | 1.02% | 0.41% | +0.61 | 60% | 1 | 0 | 10 | True | $0.0611 | $61.09 |
| page_0400 | claude-sonnet-4-6 | minimal-edit | 71 | 1.02% | 1.02% | +0.00 | 0% | 0 | 0 | 0 | False | $0.2454 | $245.44 |
| page_0400 | gemini-3.1-pro | minimal-edit | 71 | 1.02% | 0.27% | +0.75 | 73% | 1 | 1 | 10 | True | $0.0067 | $6.67 |
| page_0400 | gpt-5.5 | minimal-edit | 71 | 1.02% | 0.41% | +0.61 | 60% | 1 | 1 | 10 | True | $0.0126 | $12.58 |
| page_0400 | claude-opus-4-8 | rewrite | 71 | 1.02% | 0.27% | +0.75 | 73% | 1 | 1 | 11 | True | $0.1541 | $154.10 |
| page_0400 | claude-sonnet-4-6 | rewrite | 71 | 1.02% | 1.02% | +0.00 | 0% | 0 | 0 | 0 | False | $0.2454 | $245.36 |
| page_0400 | gemini-3.1-pro | rewrite | 71 | 1.02% | 0.20% | +0.82 | 80% | 1 | 1 | 11 | True | $0.0187 | $18.65 |
| page_0400 | gpt-5.5 | rewrite | 71 | 1.02% | 0.41% | +0.61 | 60% | 2 | 2 | 11 | True | $0.0238 | $23.75 |
| page_0499 | claude-opus-4-8 | minimal-edit | 92 | 0.38% | 0.28% | +0.10 | 27% | 2 | 2 | 7 | True | $0.0753 | $75.25 |
| page_0499 | gemini-3.1-pro | minimal-edit | 92 | 0.38% | 0.21% | +0.17 | 45% | 3 | 3 | 10 | True | $0.0087 | $8.66 |
| page_0499 | gpt-5.5 | minimal-edit | 92 | 0.38% | 0.55% | -0.17 | -45% | 6 | 6 | 10 | True | $0.0194 | $19.41 |
| page_0499 | claude-opus-4-8 | rewrite | 92 | 0.38% | 0.48% | -0.10 | -27% | 8 | 8 | 13 | True | $0.2282 | $228.19 |
| page_0499 | claude-sonnet-4-6 | rewrite | 92 | 0.38% | 0.38% | +0.00 | 0% | 0 | 0 | 0 | False | $0.1299 | $129.88 |
| page_0499 | gemini-3.1-pro | rewrite | 92 | 0.38% | 0.41% | -0.03 | -9% | 9 | 9 | 16 | True | $0.0353 | $35.32 |
| page_0499 | gpt-5.5 | rewrite | 92 | 0.38% | 1.82% | -1.45 | -382% | 16 | 15 | 20 | True | $0.0362 | $36.17 |
