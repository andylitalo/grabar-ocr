"""dots-mocr: dots.mocr (rednote, ~3B), zero-shot, via MLX on Apple Silicon.

The best open model on Armenian in GlotOCR Bench (2026). Full precision (bf16), plain
text prompt from mlx-vlm's dots_ocr README, greedy decoding.

    PYTHONPATH=. dev/ocr_eval/.venv-mlx/bin/python -m dev.ocr_eval.run_dots
"""

from __future__ import annotations

from mlx_vlm import generate, load
from mlx_vlm.prompt_utils import apply_chat_template

from .common import args, run

MODEL = "mlx-community/dots.mocr-bf16"
PROMPT = "Extract all text from this image."
MAX_TOKENS = 256  # one line; caps a runaway repetition loop


def main() -> None:
    a = args(__doc__)
    model, processor = load(MODEL)
    prompt = apply_chat_template(processor, model.config, PROMPT, num_images=1)

    def recognize(png) -> str:
        out = generate(model=model, processor=processor, prompt=prompt, image=str(png),
                       max_tokens=MAX_TOKENS, temperature=0.0, verbose=False)
        return " ".join(out.text.split())

    run("dots-mocr", {"model": MODEL, "prompt": PROMPT, "max_tokens": MAX_TOKENS, "temperature": 0},
        recognize, only_missing=not a.redo)


if __name__ == "__main__":
    main()
