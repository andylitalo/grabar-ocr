"""Write the crop of every sampled test line to runs/ocr_eval/crops/<line id>.png.

The crop is ``dev/line_review/crops.line_crop``: the same pixels the human transcribed.

    uv run python -m dev.ocr_eval.export_crops
"""

from __future__ import annotations

import json

from PIL import Image

from dev.line_review import crops, storage
from dev.line_review import transcribe as tr

from .common import CROPS_DIR


def main() -> None:
    CROPS_DIR.mkdir(parents=True, exist_ok=True)
    picks = tr.load_sample()["picks"]
    by_page: dict[int, list[str]] = {}
    for p in picks:
        by_page.setdefault(p["page"], []).append(p["id"])
    written = missing = 0
    for page, ids in sorted(by_page.items()):
        path = storage.verified_path(page)
        if not path.exists():
            missing += len(ids)
            continue
        lines = {l["id"]: l for l in json.loads(path.read_text(encoding="utf-8"))["lines"]}
        render = Image.open(storage.render_path(page)).convert("L")
        for lid in ids:
            if lid not in lines:
                missing += 1
                continue
            crops.line_crop(render, lines[lid]).save(CROPS_DIR / f"{lid}.png")
            written += 1
    print(f"{written} crops written to {CROPS_DIR}" + (f"; {missing} picks not found" if missing else ""))


if __name__ == "__main__":
    main()
