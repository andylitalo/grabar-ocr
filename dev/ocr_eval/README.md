# Phase 11 OCR engine comparison

Plan and results: `docs/phase_11_ocr_comparison.md`. Report: `reports/phase11_ocr_comparison.md`.

Every engine reads the same crops (`dev/line_review/crops.line_crop`, what the human
transcribed from) and predicts every sampled test line; `score.py` scores the lines
transcribed so far. Re-runs only predict lines an engine hasn't seen (`--redo` for all).

```bash
uv run python -m dev.ocr_eval.export_crops                          # after each "Top up sample"
.venv_ml/bin/python -m dev.ocr_eval.run_tesseract --model hye-calfa-n
.venv_ml/bin/python -m dev.ocr_eval.run_tesseract --model hye-grabar
PYTHONPATH=. dev/lineseg_survey/.venv-hyocr/bin/python -m dev.ocr_eval.run_paddle
.venv_ml/bin/python -m dev.ocr_eval.run_trocr                       # ~5 s/line on MPS
uv run python -m dev.ocr_eval.run_gemini --model flash              # ~6 s/line, API
uv run python -m dev.ocr_eval.run_gemini --model pro                # ~25 s/line, API
uv run python -m dev.ocr_eval.score                                 # writes the report
```

| file | engine | venv |
|---|---|---|
| `run_tesseract.py` | `tess-calfa-n`, `tess-grabar` | `.venv_ml` |
| `run_paddle.py` | `paddle-calfa-tiny` (recognition only) | `.venv-hyocr` |
| `run_trocr.py` | `trocr-ft` | `.venv_ml` |
| `run_gemini.py` | `gemini-flash`, `gemini-pro` | repo `.venv` |
| `score.py` | CER table, breakdowns, noise floor, worst lines | repo `.venv` |

Predictions: `data/ocr_predictions/<engine>.json` (committed). Crops: `runs/ocr_eval/crops/`
(scratch, regenerable). Surya isn't run yet: its recognizer needs llama.cpp's `llama-server`.
