# Phase 2 — hye-tesseract layout exploration

Column/page CER is a *looser* comparison than the line-level head-to-head: reading-order and line-segmentation errors fold into CER. It answers "can Tesseract handle layout at all?", not strict per-line accuracy.

| page | level | psm | CER | n_ref_chars |
|---|---|---|---|---|
| page_0251 | column | 4 | 30.9% | 1317 |
| page_0251 | column | 6 | 35.8% | 1317 |
| page_0251 | page | 1 | 39.8% | 1317 |
| page_0251 | page | 3 | 39.8% | 1317 |
| page_0400 | column | 4 | 37.5% | 1539 |
| page_0400 | column | 6 | 50.0% | 1539 |
| page_0400 | page | 1 | 37.7% | 1539 |
| page_0400 | page | 3 | 37.7% | 1539 |
| page_0499 | column | 4 | 21.6% | 2996 |
| page_0499 | column | 6 | 7.0% | 2996 |
| page_0499 | page | 1 | 12.4% | 2996 |
| page_0499 | page | 3 | 12.4% | 2996 |
| page_0550 | column | 4 | 1408.3% | 193 |
| page_0550 | column | 6 | 1390.7% | 193 |
| page_0550 | page | 1 | 1019.2% | 193 |
| page_0550 | page | 3 | 1019.2% | 193 |

## Best CER per page/level

| page | level | best psm | best CER |
|---|---|---|---|
| page_0251 | column | 4 | 30.9% |
| page_0251 | page | 3 | 39.8% |
| page_0400 | column | 4 | 37.5% |
| page_0400 | page | 3 | 37.7% |
| page_0499 | column | 6 | 7.0% |
| page_0499 | page | 3 | 12.4% |
| page_0550 | column | 6 | 1390.7% |
| page_0550 | page | 3 | 1019.2% |
