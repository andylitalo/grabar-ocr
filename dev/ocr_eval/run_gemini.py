"""gemini: Gemini, zero-shot, on each line image (Phase 2's untested frontier-VLM route).

The model is the one the corpus pipeline uses for correction (gemini-3.1-pro). Needs
GEMINI_API_KEY (read from the repo's .env if not set).

    uv run python -m dev.ocr_eval.run_gemini --model pro     # engine gemini-pro
    uv run python -m dev.ocr_eval.run_gemini --model flash   # engine gemini-flash
"""

from __future__ import annotations

import argparse
import os
import time

from google import genai
from google.genai import types

from .common import REPO_ROOT, run

MODELS = {"pro": "gemini-3.1-pro-preview", "flash": "gemini-3.5-flash"}
TIMEOUT_MS = 180_000  # a call with no timeout hung the first run
RETRIES = 3
PROMPT = (
    "This image is one printed line of Classical Armenian (Grabar), from a 1915 Jerusalem "
    "edition of the Tonatsuyts. Transcribe it exactly as printed, in Armenian Unicode. Keep "
    "abbreviation marks (՟) and abbreviations unexpanded, keep punctuation and line-end "
    "hyphens as printed, and do not correct spelling. Output only the transcription, with "
    "no quotes or commentary."
)


def _api_key() -> None:
    if os.environ.get("GEMINI_API_KEY"):
        return
    env = REPO_ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("GEMINI_API_KEY="):
            os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip().strip('"')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(MODELS), required=True)
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    model = MODELS[a.model]
    _api_key()
    client = genai.Client(http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    config = types.GenerateContentConfig(temperature=0)

    def recognize(png) -> str:
        image = types.Part.from_bytes(data=png.read_bytes(), mime_type="image/png")
        for attempt in range(RETRIES):
            try:
                resp = client.models.generate_content(model=model, contents=[image, PROMPT], config=config)
                return (resp.text or "").strip()
            except Exception as e:
                if attempt == RETRIES - 1:
                    raise
                print(f"  {png.stem}: retry after {type(e).__name__}: {str(e)[:120]}", flush=True)
                time.sleep(5 * (attempt + 1))

    run(f"gemini-{a.model}", {"model": model, "prompt": PROMPT, "temperature": 0}, recognize,
        only_missing=not a.redo, workers=8)


if __name__ == "__main__":
    main()
