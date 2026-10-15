"""Side-by-side overlays of each tool's line polygons on a page (quick visual triage).

    <any venv with Pillow>/python dev/lineseg_survey/overlay.py 457 [--tools kraken,surya] [--out DIR]

Draws every line polygon with its reading-order index; writes one PNG per page with
the tools side by side (default out: dev/lineseg_survey/overlays/).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b"]


def seg_path(tool: str, page: int) -> Path:
    if tool == "kraken":
        return common.KRAKEN_DATA / f"page_{page}" / "segmentation.json"
    return common.tool_data_dir(tool, page) / "segmentation.json"


def panel(tool: str, page: int, scale: float) -> Image.Image:
    base = Image.open(common.render_path(page)).convert("RGB")
    img = base.resize((int(base.width * scale), int(base.height * scale)))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=14)
    path = seg_path(tool, page)
    lines = json.loads(path.read_text())["lines"] if path.exists() else []
    for i, line in enumerate(lines):
        color = COLORS[i % len(COLORS)]
        pts = [(x * scale, y * scale) for x, y in line["boundary"]] or None
        if pts and len(pts) >= 3:
            draw.polygon(pts, outline=color, width=2)
        x1, y1 = line["bbox"][0] * scale, line["bbox"][1] * scale
        draw.text((x1 + 2, y1), str(line["index"]), fill=color, font=font)
    draw.rectangle([0, 0, 260, 26], fill="white")
    draw.text((6, 4), f"{tool}  p.{page}  {len(lines)} lines", fill="black", font=font)
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", help="e.g. 457 or 453-643")
    ap.add_argument("--tools", default="kraken,surya")
    ap.add_argument("--scale", type=float, default=0.45)
    ap.add_argument("--out", type=Path, default=common.SURVEY_DIR / "overlays")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    tools = args.tools.split(",")
    for page in common.parse_pages(args.pages):
        panels = [panel(t, page, args.scale) for t in tools]
        w = sum(p.width for p in panels)
        sheet = Image.new("RGB", (w, panels[0].height), "white")
        x = 0
        for p in panels:
            sheet.paste(p, (x, 0))
            x += p.width
        out = args.out / f"page_{page}.png"
        sheet.save(out)
        print(out.relative_to(common.REPO_ROOT))


if __name__ == "__main__":
    main()
