"""
app.py
FastAPI server for the Grabar line-labeling tool.

This is a local developer utility, not a model-serving endpoint, so FastAPI is
appropriate here (BentoML remains the only serving layer for ML models). HTTP
layer only: validates requests, delegates to `pipeline`/`storage`, serves the
static frontend and images.

Run:
    uv run python -m labeling_ui.app
    # or: uv run uvicorn labeling_ui.app:app --reload --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import pipeline, storage

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Grabar Line Labeler")


class Box(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class ColumnsRequest(BaseModel):
    columns: list[Box]
    deskew: bool = True
    force: bool = False


class LabelRequest(BaseModel):
    action: str  # "submit" | "empty" | "reject"
    text: str = ""


# --- page browser ------------------------------------------------------------


@app.get("/api/pages")
def list_pages() -> dict:
    numbers = storage.list_page_numbers()
    # The UI operates on the human artifact tree (page_XXXX_human): a person draws
    # the boxes and transcribes the lines. The auto tree (page_XXXX_auto) is written
    # headlessly by data_prep.auto_slice and is not edited here.
    pages = [
        {"n": n, "page_id": storage.page_artifact_id(n), "status": storage.page_status(storage.page_artifact_id(n))}
        for n in numbers
    ]
    return {
        "pages": pages,
        "min": numbers[0] if numbers else None,
        "max": numbers[-1] if numbers else None,
    }


@app.get("/api/pages/{n}")
def get_page(n: int) -> dict:
    try:
        render_path = pipeline.render_page(n)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No page PDF for page {n}")
    width, height = pipeline.page_dimensions(render_path)
    page_id = storage.page_artifact_id(n)
    return {
        "n": n,
        "page_id": page_id,
        "status": storage.page_status(page_id),
        "page_image_url": f"/api/pages/{n}/image.png",
        "image_width": width,
        "image_height": height,
        # Auto-detected boxes (falls back to hardcoded halves when not confident).
        # The frontend seeds its draggable boxes from this same `default_columns` key.
        "default_columns": pipeline.suggested_columns(n),
    }


@app.get("/api/pages/{n}/image.png")
def get_page_image(n: int) -> FileResponse:
    try:
        render_path = pipeline.render_page(n)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No page PDF for page {n}")
    return FileResponse(render_path, media_type="image/png")


@app.post("/api/pages/{n}/columns")
def crop_columns(n: int, req: ColumnsRequest) -> dict:
    if len(req.columns) != 2:
        raise HTTPException(status_code=400, detail="Exactly two columns are required")
    if not storage.page_pdf_path(n).exists():
        raise HTTPException(status_code=404, detail=f"No page PDF for page {n}")

    page_id = storage.page_artifact_id(n)
    if not req.force:
        labeled = [i for i in (1, 2) if storage.column_has_labels(page_id, i)]
        if labeled:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{page_id} already has labels in column(s) {labeled}. "
                    "Re-cropping will discard them. Resend with force=true to proceed."
                ),
            )

    columns = [b.model_dump() for b in req.columns]
    results = pipeline.crop_columns_and_lines(
        n, columns, do_deskew=req.deskew, method=storage.METHOD_HUMAN
    )
    # Persist the committed boxes as geometric ground truth for this page.
    storage.save_boxes(page_id, pipeline.deskew_angle(n), columns)
    return {
        "page_id": page_id,
        "columns": results,
        "total_lines": sum(r["line_count"] for r in results),
    }


# --- lines + labeling --------------------------------------------------------


@app.get("/api/page/{page_id}/lines")
def get_lines(page_id: str) -> dict:
    return storage.list_lines(page_id)


@app.get("/api/page/{page_id}/column/{col}/line/{line}/image")
def get_line_image(page_id: str, col: int, line: int) -> FileResponse:
    path = storage.line_image_path(page_id, col, line)
    if path is None:
        raise HTTPException(status_code=404, detail="Line image not found")
    return FileResponse(path, media_type="image/png")


@app.post("/api/page/{page_id}/column/{col}/line/{line}/label")
def label_line(page_id: str, col: int, line: int, req: LabelRequest) -> dict:
    if req.action not in ("submit", "empty", "reject"):
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")
    result = storage.apply_label(page_id, col, line, req.action, req.text)
    return {"page_id": page_id, "column": col, "line": line, **result}


# --- static frontend ---------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)


if __name__ == "__main__":
    main()
