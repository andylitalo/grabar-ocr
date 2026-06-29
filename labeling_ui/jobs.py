"""
jobs.py
In-process background job queue for the labeling UI.

When a human finishes drawing region boxes and clicks "Label and Translate", the
page is cropped+sliced synchronously (in the request) and then the slow tail of
the pipeline — OCR (tesseract) → LLM correct → translate (gemini-flash) — is run
as a BACKGROUND job so the human can move straight on to the next page.

Design: a single daemon worker thread drains a ``queue.Queue`` of job ids, running
ONE page at a time via ``pipeline.run_pages``. Strict serialization is deliberate:
``run_pages`` rebuilds the run's combined ``merged.md`` / ``translated.md`` from all
per-page artifacts on disk, and two concurrent calls would race those two files.
One worker → one ``run_pages`` at a time → the combined English document grows
monotonically and correctly. The human drawing boxes is the real rate-limiter, so
throughput is not lost in practice.

Idempotency: ``run_pages(force=False)`` reuses any cached OCR/correction/translation,
so re-enqueuing a finished page costs ~$0. A re-crop passes ``force=True`` so the
stale page-keyed OCR/correction/translation are recomputed against the new crops.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

from pipeline.api import run_pages
from pipeline.config import PipelineConfig, StageSpec

# Equivalent to CLI: --crop human --ocr tesseract --correct gemini-minimal-edit
# (--translate gemini-flash is passed to run_pages, not part of the 4-stage slug).
CONFIG = PipelineConfig(
    crop=StageSpec("human"),
    slice=StageSpec("projection"),
    ocr=StageSpec("tesseract"),
    correct=StageSpec("gemini-minimal-edit"),
)
TRANSLATOR = "gemini-flash"


@dataclass
class Job:
    id: str
    page: int
    status: str  # queued | running | done | failed
    force: bool = False
    error: str | None = None
    cost: float | None = None
    enqueued_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    def snapshot(self) -> dict:
        # Public view excludes the internal `force` flag.
        d = asdict(self)
        d.pop("force", None)
        return d


_q: "queue.Queue[str | None]" = queue.Queue()  # job ids; None = stop sentinel
_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_worker: threading.Thread | None = None


def enqueue(page: int, *, force: bool = False) -> dict:
    """Register a queued job for ``page`` and hand its id to the worker."""
    job = Job(id=uuid.uuid4().hex[:12], page=page, status="queued", force=force)
    with _lock:
        _jobs[job.id] = job
        snap = job.snapshot()
    _q.put(job.id)
    return snap


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return job.snapshot() if job else None


def list_jobs() -> list[dict]:
    """All jobs, newest first (lock-guarded copies)."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.enqueued_at, reverse=True)
        return [j.snapshot() for j in jobs]


def _set(job_id: str, **changes) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        for k, v in changes.items():
            setattr(job, k, v)


def _run_job(job_id: str, page: int, force: bool) -> None:
    _set(job_id, status="running", started_at=time.time())
    try:
        res = run_pages([page], CONFIG, translate=TRANSLATOR, force=force)
        if res["credit_exhausted"]:
            msg = f"Gemini credits exhausted at page {res['stopped_at']}"
            _set(job_id, status="failed", error=msg, finished_at=time.time())
        elif res["failed"]:
            f = res["failed"][0]
            _set(job_id, status="failed",
                 error=f"{f.get('stage', '')}: {f.get('reason', '')}".strip(": "),
                 finished_at=time.time())
        elif res["deferred"]:
            d = res["deferred"][0]
            _set(job_id, status="failed",
                 error=f"crop deferred: {d.get('reason', '')}", finished_at=time.time())
        else:
            _set(job_id, status="done", cost=res["translation_cost"],
                 finished_at=time.time())
    except Exception as exc:  # noqa: BLE001 — isolate any per-job failure
        _set(job_id, status="failed", error=str(exc)[:300], finished_at=time.time())


def _worker_loop() -> None:
    while True:
        job_id = _q.get()
        try:
            if job_id is None:  # stop sentinel
                return
            with _lock:
                job = _jobs.get(job_id)
            if job is not None:
                _run_job(job_id, job.page, job.force)
        finally:
            _q.task_done()


def start_worker() -> None:
    """Spawn the single daemon worker thread (idempotent)."""
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    _worker = threading.Thread(target=_worker_loop, name="label-translate-worker",
                               daemon=True)
    _worker.start()


def stop_worker() -> None:
    """Signal the worker to exit and join it (best-effort, bounded)."""
    global _worker
    if _worker is None:
        return
    _q.put(None)
    _worker.join(timeout=5.0)
    _worker = None
