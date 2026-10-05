"""Phase 9 review UI: fix the paddle-filled baseline, then verify the result.

Run from the repo root (needs the repo venv for shapely):

    uv run python -m dev.line_review.app        # http://127.0.0.1:8092

Every edit is saved as an op (``materialize.py``); the server re-materializes on each
save and the page shows the result. See docs/phase_9_line_segmentation_review.md.

``/transcribe`` is the Phase 10 workflow: type the text of verified lines
(docs/phase_10_ocr_test_set.md).
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from . import crops
from . import materialize as mz
from . import storage
from . import transcribe as tr

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Phase 9 line review")


class OpsRequest(BaseModel):
    ops: list[dict]
    section_titles: list[dict] = []


class StatusRequest(BaseModel):
    status: str


class TranscriptionRequest(BaseModel):
    text: str
    status: str = "done"


class RecheckRequest(BaseModel):
    text: str


CONTRIBUTOR = "maintainer"  # set by --contributor; stored as ``by`` on each transcription


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
        review, _ = storage.save_ops(page, req.ops, req.section_titles)
    except mz.OpError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except storage.StateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _payload(page, review)


@app.post("/api/pages/{page}/status")
def post_status(page: int, req: StatusRequest) -> dict:
    _page_or_404(page)
    try:
        review = storage.set_status(page, req.status)
    except (storage.StateError, mz.OpError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _payload(page, review)


# --- Phase 10: transcription ------------------------------------------------------


def _verified_pages() -> list[dict]:
    """Verified-lines records for pages whose review is currently ``verified``."""
    out = []
    for page, status in storage.page_statuses().items():
        path = storage.verified_path(page)
        if status == "verified" and path.exists():
            out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def _verified_line(line_id: str) -> tuple[dict, dict]:
    """(the line, its page record) from data/verified_lines, or 404."""
    page = tr.page_of(line_id)
    path = storage.verified_path(page)
    if path.exists():
        rec = json.loads(path.read_text(encoding="utf-8"))
        for line in rec["lines"]:
            if line["id"] == line_id:
                return line, rec
    raise HTTPException(status_code=404, detail=f"No verified line {line_id}")


def _png(img: Image.Image) -> Response:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


def _transcribe_state() -> dict:
    sample = tr.load_sample()
    pool = tr.candidates(_verified_pages())
    recheck = set(tr.recheck_ids(sample))
    pages: dict[int, dict] = {}
    picks = []
    # Serve in rank order, not pick order: picks are appended stratum by stratum, so pick
    # order would serve every body line before the first display or drop-cap line.
    for p in sorted(sample["picks"], key=lambda p: tr.rank(sample["seed"], p["id"])):
        if p["page"] not in pages:
            pages[p["page"]] = tr.load_page(p["page"])
        rec = pages[p["page"]].get(p["id"])
        picks.append({**p, "status": rec["status"] if rec else "pending",
                      "recheck": p["id"] in recheck,
                      "rechecked": bool(rec and "recheck" in rec)})
    strata = {name: {"quota": q, "picked": sum(p["stratum"] == name for p in picks),
                     "done": sum(p["stratum"] == name and p["status"] != "pending" for p in picks),
                     "pool": sum(c["stratum"] == name for c in pool)}
              for name, q in sample["quotas"].items()}
    return {"picks": picks, "strata": strata, "missing": tr.missing_picks(sample, pool),
            "per_page": sample.get("per_page"), "contributor": CONTRIBUTOR}


@app.get("/transcribe")
def transcribe_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "transcribe.html")


@app.get("/api/transcribe/state")
def transcribe_state() -> dict:
    return _transcribe_state()


@app.post("/api/transcribe/sample")
def top_up_sample() -> dict:
    tr.save_sample(tr.top_up(tr.load_sample(), tr.candidates(_verified_pages())))
    return _transcribe_state()


@app.get("/api/lines/{line_id}")
def get_line(line_id: str) -> dict:
    line, rec = _verified_line(line_id)
    return {"id": line_id, "page": rec["page"], "bbox": line["bbox"], "initial": line.get("initial"),
            "transcription": tr.load_line(line_id)}


@app.get("/api/lines/{line_id}/crop.png")
def get_line_crop(line_id: str) -> Response:
    line, rec = _verified_line(line_id)
    return _png(crops.line_crop(Image.open(storage.render_path(rec["page"])).convert("L"), line))


@app.get("/api/lines/{line_id}/context.png")
def get_line_context(line_id: str) -> Response:
    line, rec = _verified_line(line_id)
    page = Image.open(storage.render_path(rec["page"]))
    return _png(crops.context_crop(page, line, rec["lines"]))


@app.put("/api/transcribe/lines/{line_id}")
def put_transcription(line_id: str, req: TranscriptionRequest) -> dict:
    _verified_line(line_id)
    try:
        return tr.save_line(line_id, text=req.text, status=req.status, by=CONTRIBUTOR)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/transcribe/lines/{line_id}/recheck")
def put_recheck(line_id: str, req: RecheckRequest) -> dict:
    try:
        return tr.save_recheck(line_id, text=req.text, by=CONTRIBUTOR)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    global CONTRIBUTOR
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--contributor", default="maintainer",
                    help="name stored as `by` on each transcription")
    args = ap.parse_args()
    CONTRIBUTOR = args.contributor
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
