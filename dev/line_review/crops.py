"""Line images for verified lines: the one crop every consumer uses.

The Phase 10 transcription UI and the OCR engine runs both read lines through
``line_crop``, so a human and every engine see exactly the same pixels.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

PAD = 6  # px around the line's bbox


def line_crop(page: Image.Image, line: dict, pad: int = PAD) -> Image.Image:
    """``line``'s bbox (+ ``pad``) from ``page``, with pixels outside its polygon whitened.

    Whitening keeps neighbouring lines' ascenders and descenders out of the crop.
    """
    x1, y1, x2, y2 = (int(round(v)) for v in line["bbox"])
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2, y2 = min(page.width, x2 + pad), min(page.height, y2 + pad)
    region = page.crop((x1, y1, x2, y2))
    mask = Image.new("L", region.size, 0)
    ImageDraw.Draw(mask).polygon([(x - x1, y - y1) for x, y in line["boundary"]], fill=255)
    white = Image.new(region.mode, region.size, 255 if region.mode == "L" else (255,) * len(region.mode))
    return Image.composite(region, white, mask)


def context_crop(page: Image.Image, line: dict, lines: list[dict], margin: float = 2.5) -> Image.Image:
    """The page around ``line`` (a few line heights above and below, its column's width),
    with the line outlined, for reading hard letters in context."""
    x1, y1, x2, y2 = line["bbox"]
    h = y2 - y1
    top, bottom = max(0, y1 - margin * h), min(page.height, y2 + margin * h)
    near = [l["bbox"] for l in lines if l["bbox"][3] > top and l["bbox"][1] < bottom
            and min(l["bbox"][2], x2) - max(l["bbox"][0], x1) > 0]
    left = max(0, min([x1] + [b[0] for b in near]) - 30)
    right = min(page.width, max([x2] + [b[2] for b in near]) + 30)
    img = page.convert("RGB").crop((int(left), int(top), int(right), int(bottom)))
    ImageDraw.Draw(img).polygon([(x - left, y - top) for x, y in line["boundary"]],
                                outline=(255, 140, 0), width=3)
    return img
