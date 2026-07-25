"""FastAPI app for reviewing kraken line-segmentation output.

Read-only w.r.t. kraken: it serves the pre-generated ``render.png`` +
``segmentation.json`` (produced by ``dev/kraken_segment.py``) and lets a human
click each segmented line and categorize errors — 1=over-segmentation,
2=under-segmentation, 3=non-text — persisting them to
``dev/kraken_review/reviews/page_<N>.review.json``.

Run from the repo root (no kraken needed; only FastAPI/uvicorn/Pillow):

    uv run python -m dev.kraken_review.app

then open http://127.0.0.1:8090
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import storage

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Kraken Line-Segmentation Review")


class MissedLine(BaseModel):
    id: str
    box: list[float]  # [x1, y1, x2, y2] in full-resolution page pixels


class ReviewRequest(BaseModel):
    # kraken line id ("line_003") -> category number (1/2/3)
    flags: dict[str, int] = {}
    # human-drawn boxes for lines kraken missed entirely
    missed: list[MissedLine] = []


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/pages")
def get_pages() -> dict:
    return {"pages": storage.list_pages()}


@app.get("/api/pages/{page}/image.png")
def get_image(page: int) -> FileResponse:
    path = storage.render_path(page)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No render for page {page}")
    return FileResponse(path, media_type="image/png")


@app.get("/api/pages/{page}/segmentation")
def get_segmentation(page: int) -> dict:
    try:
        return storage.load_segmentation(page)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/pages/{page}/review")
def get_review(page: int) -> dict:
    return storage.load_review(page)


@app.post("/api/pages/{page}/review")
def post_review(page: int, req: ReviewRequest) -> dict:
    try:
        return storage.save_review(page, req.flags, [m.model_dump() for m in req.missed])
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8090)


if __name__ == "__main__":
    main()
