"""trocr-ft: TrOCR fine-tuned on 500 lines of Ժամագիրք Ատենի (finetune_phase4_scale_500).

Loading, checkpoint choice and beam search are ``ml_vision/scripts/predict_lines.py``'s,
except ``max_length`` 128 (64 tokens can cut off this book's longer lines).

    .venv_ml/bin/python -m dev.ocr_eval.run_trocr
"""

from __future__ import annotations

import sys

import torch
from PIL import Image

from .common import REPO_ROOT, args, run

sys.path.insert(0, str(REPO_ROOT / "ml_vision" / "scripts"))
from grabar_generation import NUM_BEAMS, configure_generation  # noqa: E402
from predict_lines import BASE_ID, DEFAULT_CKPT_DIR, pick_checkpoint  # noqa: E402
from transformers import TrOCRProcessor, VisionEncoderDecoderModel  # noqa: E402

MAX_LENGTH = 128


def main() -> None:
    a = args(__doc__)
    ckpt = pick_checkpoint(DEFAULT_CKPT_DIR)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor = TrOCRProcessor.from_pretrained(BASE_ID)
    model = VisionEncoderDecoderModel.from_pretrained(ckpt).to(device).eval()
    configure_generation(model)

    def recognize(png) -> str:
        pixels = processor(images=Image.open(png).convert("RGB"), return_tensors="pt").pixel_values.to(device)
        with torch.no_grad():
            ids = model.generate(pixels, max_length=MAX_LENGTH, num_beams=NUM_BEAMS)
        return processor.batch_decode(ids, skip_special_tokens=True)[0].strip()

    run("trocr-ft", {"checkpoint": str(ckpt.relative_to(REPO_ROOT)), "base": BASE_ID,
                     "num_beams": NUM_BEAMS, "max_length": MAX_LENGTH}, recognize, only_missing=not a.redo)


if __name__ == "__main__":
    main()
