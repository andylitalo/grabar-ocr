"""Phase 9 review UI: fix the paddle-filled baseline, then verify the result.

Run from the repo root (needs the repo venv for shapely):

    uv run python -m dev.line_review.app        # http://127.0.0.1:8092

Every edit is saved as an op (``materialize.py``); the server re-materializes on each
save and the page shows the result. See docs/phase_9_line_segmentation_review.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import materialize as mz
from . import storage

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Phase 9 line review")


class OpsRequest(BaseModel):
    ops: list[dict]
    section_titles: list[dict] = []
    revision: int | None = None  # the review revision these ops were built on


class StatusRequest(BaseModel):
    status: str
    revision: int | None = None


def _payload(page: int, review: dict) -> dict:
    seg = storage.load_baseline(page)
    error, page_number = None, None
    try:
        page_el = mz.materialize_page(mz.baseline_lines(seg), review["ops"],
                                      review.get("section_titles", []))
        page_number = page_el["page_number"]
        lines = page_el["lines"]
    except mz.OpError as e:  # only if the baseline changed under saved ops
        lines, error = [], str(e)
    baseline = {l["id"]: l for l in seg["lines"]}
    deleted = {op["line"] for op in review["ops"] if op.get("op") == "delete"}
    ids = review.get("ids", {})
    return {
        "page": page,
        "width": seg["width"],
        "height": seg["height"],
        "status": review["status"],
        "revision": review.get("revision", 0),
        "ops": review["ops"],
        "section_titles": review.get("section_titles", []),
        "page_number": page_number,
        "expected_page_number": str(page - storage.PRINTED_OFFSET),
        "lines": [
            {"key": l["key"], "order": n, "id": ids.get(l["key"]), "boundary": l["boundary"],
             "bbox": l["bbox"], "source": l["source"], "initial": l.get("initial"),
             "edited": l["key"] not in baseline or l["boundary"] != baseline[l["key"]]["boundary"]}
            for n, l in enumerate(lines, start=1)
        ],
        "ghosts": [{"key": k, "boundary": baseline[k]["boundary"], "bbox": baseline[k]["bbox"]}
                   for k in sorted(deleted) if k in baseline],
        "baseline_changed": storage.baseline_changed(review),
        "blank_marker": storage.blank_marker(page),
        "error": error,
        "used_add_keys": sorted(storage.used_add_keys(review)),
    }


def _page_or_404(page: int) -> None:
    if not storage.baseline_path(page).exists():
        raise HTTPException(status_code=404, detail=f"No baseline for page {page}")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/pages")
def get_pages() -> dict:
    return {"statuses": {str(p): s for p, s in storage.page_statuses().items()}}


@app.get("/api/pages/{page}/image.png")
def get_image(page: int) -> FileResponse:
    path = storage.render_path(page)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No render for page {page}")
    return FileResponse(path, media_type="image/png")


@app.get("/api/pages/{page}")
def get_page(page: int) -> dict:
    _page_or_404(page)
    return _payload(page, storage.load_review(page))


@app.put("/api/pages/{page}/ops")
def put_ops(page: int, req: OpsRequest) -> dict:
    _page_or_404(page)
    try:
        review, _ = storage.save_ops(page, req.ops, req.section_titles, req.revision)
    except mz.OpError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except storage.StateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _payload(page, review)


@app.post("/api/pages/{page}/status")
def post_status(page: int, req: StatusRequest) -> dict:
    _page_or_404(page)
    try:
        review = storage.set_status(page, req.status, req.revision)
    except (storage.StateError, mz.OpError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _payload(page, review)


# --- Phase 10: transcription ------------------------------------------------------


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8092)
    args = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
