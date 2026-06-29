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

from . import jobs, pipeline, storage

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Grabar Line Labeler")


@app.on_event("startup")
def _start_worker() -> None:
    jobs.start_worker()


@app.on_event("shutdown")
def _stop_worker() -> None:
    jobs.stop_worker()


class Box(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class RegionIn(BaseModel):
    type: str  # header | single | left | right
    box: Box   # the single crop box (drawn tight to the text)


class ColumnsRequest(BaseModel):
    # Ordered, typed regions (top-to-bottom; left before right within a band). Each
    # region carries one box — the crop region. No box is persisted: it is read only
    # by line-slicing here, never downstream (reading order/type live in the
    # region_NN_<type> dir names).
    regions: list[RegionIn]
    deskew: bool = True
    force: bool = False
    # Human reference-line residual (deg): un-skews the render before cropping.
    manual_angle: float = 0.0


class LabelRequest(BaseModel):
    action: str  # "submit" | "empty" | "reject"
    text: str = ""


class NoncharTruthRequest(BaseModel):
    # "<region_key>/line_NNN" -> "empty" (non-character) | "character" (real Grabar)
    verdicts: dict[str, str]


class BlankRequest(BaseModel):
    blank: bool = True  # True = mark page blank; False = unmark


# --- page browser ------------------------------------------------------------


@app.get("/api/pages")
def list_pages() -> dict:
    numbers = storage.list_page_numbers()
    # The UI operates on the human artifact tree (page_XXXX_human): a person draws
    # the boxes and transcribes the lines. The auto tree (page_XXXX_auto) is written
    # headlessly by data_prep.auto_slice and is not edited here.
    pages = [
        {
            "n": n,
            "page_id": storage.page_artifact_id(n),
            "status": storage.page_status(storage.page_artifact_id(n)),
            "blank": storage.is_blank(n),
            # Auto tree (page_XXXX_auto) status for the Phase A detector-validation
            # entry point: none / sliced / verified. Human fields are unchanged.
            "has_auto": storage.has_auto_lines(n),
            "auto_status": storage.auto_status(n),
        }
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
        "blank": storage.is_blank(n),
        "page_image_url": f"/api/pages/{n}/image.png",
        "image_width": width,
        "image_height": height,
        # Auto-detected typed regions to seed the annotator ([{type, box}]); each
        # box seeds the region's min and max. Falls back to two halves when the
        # detector is not confident. `default_columns` kept for back-compat.
        "default_regions": pipeline.suggested_regions(n),
        "default_columns": pipeline.suggested_columns(n),
        # Phase A: auto-sliced tree status, so the browser can offer "Verify auto slice".
        "has_auto": storage.has_auto_lines(n),
        "auto_status": storage.auto_status(n),
        "auto_page_id": storage.page_artifact_id(n, storage.METHOD_AUTO),
    }


@app.get("/api/pages/{n}/image.png")
def get_page_image(n: int, angle: float = 0.0) -> FileResponse:
    """The deskewed render, optionally further un-skewed by the human ``angle`` (deg).

    The region annotator re-fetches with ``angle`` set when the user aligns the
    deskew reference line, so boxes are drawn on the same frame the crop uses.
    """
    try:
        render_path = pipeline.preview_render(n, angle)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No page PDF for page {n}")
    return FileResponse(render_path, media_type="image/png")


@app.post("/api/pages/{n}/blank")
def mark_blank(n: int, req: BlankRequest) -> dict:
    """Mark (or unmark) a source page as blank — no Grabar to digitize. Records a
    marker JSON under data/pages/blank/ so the page is tracked as handled and
    skipped by the crop worklist."""
    if not storage.page_pdf_path(n).exists():
        raise HTTPException(status_code=404, detail=f"No page PDF for page {n}")
    blank = storage.set_blank(n, req.blank)
    return {"n": n, "blank": blank}


_REGION_TYPES = ("header", "single", "left", "right")


def _crop_page(n: int, req: ColumnsRequest) -> dict:
    """Crop+slice a page from its drawn region boxes; shared by /columns and
    /label-and-translate. Raises the same HTTPExceptions for both callers."""
    if not req.regions:
        raise HTTPException(status_code=400, detail="At least one region is required")
    bad = [r.type for r in req.regions if r.type not in _REGION_TYPES]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown region type(s): {bad}")
    if not storage.page_pdf_path(n).exists():
        raise HTTPException(status_code=404, detail=f"No page PDF for page {n}")

    page_id = storage.page_artifact_id(n)
    if not req.force and storage.page_has_labels(page_id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{page_id} already has labeled lines. "
                "Re-cropping will discard them. Resend with force=true to proceed."
            ),
        )

    # Crop each region from its single box; no box is persisted (line-slicing is the
    # only reader — downstream uses the region_NN_<type> dir names + line crops).
    crop_boxes = [r.box.model_dump() for r in req.regions]
    types = [r.type for r in req.regions]
    results = pipeline.crop_columns_and_lines(
        n, crop_boxes, do_deskew=req.deskew, method=storage.METHOD_HUMAN,
        region_types=types, manual_angle=req.manual_angle,
    )
    return {
        "page_id": page_id,
        "regions": results,
        "total_lines": sum(r["line_count"] for r in results),
    }


@app.post("/api/pages/{n}/columns")
def crop_columns(n: int, req: ColumnsRequest) -> dict:
    return _crop_page(n, req)


@app.post("/api/pages/{n}/label-and-translate", status_code=202)
def label_and_translate(n: int, req: ColumnsRequest) -> dict:
    """Crop+slice the page now, then enqueue OCR→correct→translate as a background job.

    Returns immediately (202) with the crop result plus the queued job, so the human
    can move straight to the next page while the worker digitizes + translates this one.
    """
    result = _crop_page(n, req)
    job = jobs.enqueue(n, force=req.force)
    return {**result, "job": job}


@app.get("/api/jobs")
def list_jobs() -> dict:
    return {"jobs": jobs.list_jobs()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    return job


# --- lines + labeling --------------------------------------------------------


@app.get("/api/page/{page_id}/lines")
def get_lines(page_id: str) -> dict:
    info = storage.list_lines(page_id)
    # Additively merge the per-line detector verdict + any saved human truth so the
    # verify-non-character mode can seed each line. Current consumers ignore the new
    # keys, so the existing transcription workflow is unaffected.
    verdicts = pipeline.line_nonchar_verdicts(page_id)
    truth = storage.load_nonchar_truth(page_id)
    truth_lines = (truth or {}).get("lines", {})
    for line in info["lines"]:
        line_id = line["line_id"]
        v = verdicts.get(line_id)
        if v is not None:
            line["non_character"] = v["non_character"]
            line["glyph_count"] = v["glyph_count"]
            line["ink_ratio"] = v["ink_ratio"]
        t = truth_lines.get(line_id)
        if t is not None:
            line["truth"] = t["truth"]
    info["nonchar_verified"] = truth is not None
    return info


@app.post("/api/page/{page_id}/nonchar-truth")
def submit_nonchar_truth(page_id: str, req: NoncharTruthRequest) -> dict:
    """Persist the human non-character verdicts for an auto page + return a scorecard.

    Recomputes the detector snapshot at submit time (so the saved truth records both
    the human verdict and the detector's verdict + features), writes
    nonchar_truth.json, and returns TP/FP/FN/TN for an instant in-UI summary.
    Positive class = non-character. FP (detector flags a real line) must be 0.
    """
    for line_id, verdict in req.verdicts.items():
        if verdict not in ("empty", "character"):
            raise HTTPException(
                status_code=400, detail=f"Bad verdict {verdict!r} for {line_id}"
            )

    verdicts = pipeline.line_nonchar_verdicts(page_id)
    if not verdicts:
        raise HTTPException(status_code=404, detail=f"No line crops for {page_id}")

    storage.save_nonchar_truth(
        page_id, req.verdicts, pipeline.detector_meta(), verdicts
    )

    tp = fp = fn = tn = 0
    for line_id, verdict in req.verdicts.items():
        det = bool(verdicts.get(line_id, {}).get("non_character", False))
        human_nonchar = verdict == "empty"
        if det and human_nonchar:
            tp += 1
        elif det and not human_nonchar:
            fp += 1
        elif not det and human_nonchar:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "page_id": page_id,
        "counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "total": len(req.verdicts)},
        "precision": precision,
        "recall": recall,
    }


@app.get("/api/page/{page_id}/region/{region}/line/{line}/image")
def get_line_image(page_id: str, region: str, line: int) -> FileResponse:
    path = storage.line_image_path(page_id, region, line)
    if path is None:
        raise HTTPException(status_code=404, detail="Line image not found")
    return FileResponse(path, media_type="image/png")


@app.post("/api/page/{page_id}/region/{region}/line/{line}/label")
def label_line(page_id: str, region: str, line: int, req: LabelRequest) -> dict:
    if req.action not in ("submit", "empty", "reject"):
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")
    result = storage.apply_label(page_id, region, line, req.action, req.text)
    return {"page_id": page_id, "region": region, "line": line, **result}


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
