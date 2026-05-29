"""Baseline CER evaluation: off-the-shelf TrOCR on Phase 0 line crops."""

from pathlib import Path
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
from jiwer import cer
import torch

MODEL_ID = "microsoft/trocr-base-handwritten"
GOLDEN_DIR = Path("data/golden/page_0001")

processor = TrOCRProcessor.from_pretrained(MODEL_ID)
model = VisionEncoderDecoderModel.from_pretrained(MODEL_ID)
model.eval()

# Use MPS on Apple Silicon if available
device = "mps" if torch.backends.mps.is_available() else "cpu"
model = model.to(device)

predictions = []
references = []
empty_line_predictions = []  # section markers — no reference text

for txt_path in sorted(GOLDEN_DIR.glob("*.txt")):
    ground_truth = txt_path.read_text(encoding="utf-8").strip()
    img_path = txt_path.with_suffix(".png")
    image = Image.open(img_path).convert("RGB")
    pixel_values = processor(images=image, return_tensors="pt").pixel_values.to(device)

    with torch.no_grad():
        generated_ids = model.generate(pixel_values)
    prediction = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

    if not ground_truth:
        # Section marker — excluded from CER (empty reference = division by zero)
        empty_line_predictions.append((img_path.name, prediction))
        print(f"{img_path.name}: '{prediction}' | GT: <section marker>")
    else:
        predictions.append(prediction)
        references.append(ground_truth)
        print(f"{img_path.name}: '{prediction}' | GT: '{ground_truth}'")

overall_cer = cer(references, predictions)
print(f"\n=== Baseline CER: {overall_cer:.4f} ({overall_cer * 100:.1f}%) ===")
print(f"Lines evaluated: {len(references)}")
if empty_line_predictions:
    print(f"\n--- Section marker predictions (excluded from CER) ---")
    for name, pred in empty_line_predictions:
        status = "correctly empty" if not pred else f"hallucinated: '{pred}'"
        print(f"  {name}: {status}")
