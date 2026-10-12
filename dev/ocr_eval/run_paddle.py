"""paddle-calfa-tiny: Calfa's PP-OCR recognition model, run recognition-only on each crop.

A crop is already exactly one verified line, so no text detection runs (hye-open-ocr's
``PaddleRecognizer`` would detect lines inside the crop first, which can split a line or
drop its drop cap). The model directory and name come from ``armenian_ocr`` itself.

    dev/lineseg_survey/.venv-hyocr/bin/python -m dev.ocr_eval.run_paddle
"""

from __future__ import annotations

from armenian_ocr import models
from armenian_ocr.recognition.paddle import _rec_model_name_from_dir
from paddleocr import TextRecognition

from .common import args, run


def main() -> None:
    a = args(__doc__)
    rec_dir = models.get_paddle_rec_dir()
    name = _rec_model_name_from_dir(str(rec_dir))
    model = TextRecognition(model_dir=str(rec_dir), model_name=name)

    def recognize(png) -> str:
        (res,) = model.predict(str(png))
        return res["rec_text"].strip()

    run("paddle-calfa-tiny", {"model": name, "model_dir": rec_dir.name, "mode": "recognition-only"},
        recognize, only_missing=not a.redo)


if __name__ == "__main__":
    main()
