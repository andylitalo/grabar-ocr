"""
Pipeline orchestrator — chains the four stages for a set of page numbers and writes
the run artifacts.

Three of the four stages run in-process in the base venv (crop/slice/correct). OCR
is the only stage that crosses an interpreter boundary: it needs torch, which lives
only in ``.venv_ml``, so it is launched as a per-page subprocess against that
interpreter directly (NOT ``uv run`` — see predict_lines.py's docstring on why uv
re-syncs the wrong venv). The base-venv process never imports torch.

Stages that already wrote their output (baseline predictions.json, corrected
predictions.json) are reused unless ``force`` — re-runs are fast and never re-spend
LLM tokens or re-load the OCR model needlessly.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pipeline import artifacts, scoring
from pipeline.config import PipelineConfig
from pipeline.registry import CORRECTORS, CROPPERS, OCR_ENGINES, SLICERS, TRANSLATORS

REPO = Path(__file__).resolve().parents[1]
PRED_BASE = REPO / "data" / "predictions"
ML_PYTHON = REPO / ".venv_ml" / "bin" / "python"


@dataclass
class RunResult:
    config: PipelineConfig
    run_dir: Path
    pages: list[int]
    page_ids: list[str] = field(default_factory=list)
    deferred: list[dict] = field(default_factory=list)
    merged_doc: Path | None = None
    scorecard: Path | None = None
    needs_labeling: list[str] = field(default_factory=list)
    per_page: dict[str, Path] = field(default_factory=dict)
    scores: list[dict] = field(default_factory=list)
    translations: dict[int, Path] = field(default_factory=dict)
    translated_doc: Path | None = None
    translation_cost: float = 0.0
    worklist: Path | None = None
    failed: list[dict] = field(default_factory=list)
    credit_exhausted: bool = False
    stopped_at: int | None = None


# Quota / credit / billing exhaustion tokens (case-insensitive substring match on
# the exception message). Mirrors the insufficient_quota special-case already in
# ml_vision/scripts/llm_correct._retry — these are PERMANENT failures (refill needed),
# not the transient 429/5xx that _retry already backs off on.
_CREDIT_TOKENS = (
    "insufficient_quota", "resource_exhausted", "quota", "billing",
    "credit", "payment", "402",
)


def _is_credit_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like exhausted API credits / quota / billing (permanent)."""
    msg = str(exc).lower()
    return any(tok in msg for tok in _CREDIT_TOKENS)


def _run_ocr(page_id: str, ocr_impl, *, force: bool) -> tuple[str, bool]:
    """Run stage-3 OCR in .venv_ml via subprocess. Returns (baseline_tag, reused).

    One retry before surfacing CalledProcessError — the MPS subprocess can fail
    transiently (model load races, a transient device hiccup) over a multi-hour
    book run; a second attempt costs one page's OCR, not the whole batch.
    """
    tag = ocr_impl.meta["tag"]
    script = ocr_impl.meta["script"]
    out_json = PRED_BASE / tag / page_id / "predictions.json"
    if out_json.exists() and not force:
        return tag, True
    cmd = [str(ML_PYTHON), script, "--page", page_id, "--model-tag", tag]
    try:
        subprocess.run(cmd, cwd=REPO, check=True)
    except subprocess.CalledProcessError as e:
        print(f"  RETRY OCR {page_id} (exit {e.returncode})")
        subprocess.run(cmd, cwd=REPO, check=True)
    return tag, False


def collect_rows(page_id: str, ocr_tag: str, correct_tag: str) -> list[dict]:
    """Per-line rows joining baseline OCR (ocr_beam, non_character) with corrected text.

    Baseline predictions.json keys are line-ids in reading order (insertion order),
    so the rows come out in global reading order. When correct_tag == ocr_tag (the
    "none" corrector) the corrected text is the baseline beam itself.
    """
    base = json.loads((PRED_BASE / ocr_tag / page_id / "predictions.json").read_text(encoding="utf-8"))["lines"]
    corr_path = PRED_BASE / correct_tag / page_id / "predictions.json"
    corr = (
        json.loads(corr_path.read_text(encoding="utf-8"))["lines"]
        if correct_tag != ocr_tag and corr_path.exists()
        else base
    )

    rows: list[dict] = []
    for idx, (line_id, b) in enumerate(base.items()):
        corrected = corr.get(line_id, {}).get("pred_beam", b.get("pred_beam", ""))
        rows.append(
            {
                "index": idx,
                "line_id": line_id,
                "region": line_id.split("/")[0] if "/" in line_id else "",
                "column": b.get("column"),
                "non_character": bool(b.get("non_character")),
                "ocr_beam": b.get("pred_beam", ""),
                "corrected": corrected,
                "ref": None,
                "cer": None,
            }
        )
    return rows


def _process_page(n: int, ctx: dict) -> dict:
    """Run crop→OCR→correct→(translate) for one page. Pure worker: writes this page's
    own artifacts (which double as the idempotency cache) and returns a result dict;
    it never mutates shared RunResult state, so it is safe to run in a thread pool.

    Returns ``{"n", "status": deferred|ok|failed|credit, ...}``.
    """
    page_id = f"page_{n:04d}"  # best-effort id for error rows before crop resolves it
    stage = "crop"
    try:
        crop = ctx["crop_impl"].run(n, force=ctx["force"], **ctx["config"].crop.params)
        page_id = crop["page_id"]
        if crop["deferred"]:
            return {"n": n, "status": "deferred", "page_id": page_id, "reason": crop["reason"]}

        stage = "ocr"
        ocr_tag, _ = _run_ocr(page_id, ctx["ocr_impl"], force=ctx["force"])
        stage = "correct"
        corr = ctx["correct_impl"].run(
            page_id, baseline_tag=ocr_tag, force=ctx["force"], **ctx["correct_params"]
        )
        correct_tag = corr["correct_tag"]

        stage = "collect"
        rows = collect_rows(page_id, ocr_tag, correct_tag)
        score = scoring.score_page(page_id, rows)
        label_msg = scoring.detect_needs_labeling(page_id)
        page_path = artifacts.write_lines_json(
            ctx["run_dir"], page_id, rows,
            config_slug=ctx["slug"], ocr_tag=ocr_tag, correct_tag=correct_tag, score=score,
        )

        out = {"n": n, "status": "ok", "page_id": page_id, "ocr_tag": ocr_tag,
               "correct_tag": correct_tag, "rows": rows, "score": score,
               "label_msg": label_msg, "page_path": page_path,
               "translation": None, "tr_path": None, "cost": 0.0, "tr_reused": False}

        if ctx["do_translate"]:
            stage = "translate"
            page_text = "\n".join(r["corrected"] for r in rows if not r["non_character"])
            tr = ctx["translate_impl"].run(
                page_id, correct_tag=correct_tag, page_text=page_text,
                force=ctx["force"], **ctx["translate_params"],
            )
            out["translation"] = tr["text"]
            out["cost"] = tr["cost"]
            out["tr_reused"] = tr["reused"]
            out["tr_path"] = artifacts.write_translation(
                ctx["run_dir"], ctx["translate_impl"].slug, n, tr["text"]
            )
        return out

    except Exception as exc:  # noqa: BLE001 — isolate any per-page failure
        status = "credit" if _is_credit_error(exc) else "failed"
        return {"n": n, "status": status, "page_id": page_id, "stage": stage,
                "exc": str(exc)}


def run(
    pages: list[int],
    config: PipelineConfig,
    *,
    translate: str = "none",
    force: bool = False,
    concurrency: int = 1,
) -> RunResult:
    crop_impl = CROPPERS[config.crop.impl]
    slice_impl = SLICERS[config.slice.impl]
    ocr_impl = OCR_ENGINES[config.ocr.impl]
    correct_impl = CORRECTORS[config.correct.impl]
    correct_params = {**correct_impl.meta.get("params", {}), **config.correct.params}

    translate_impl = TRANSLATORS[translate]
    translate_params = translate_impl.meta.get("params", {})
    do_translate = translate != "none"

    slug = config.slug()
    run_dir = artifacts.RUNS_DIR / slug
    result = RunResult(config=config, run_dir=run_dir, pages=list(pages))

    ocr_tag = ocr_impl.meta["tag"]
    correct_tag = ocr_tag
    ctx = {
        "config": config, "crop_impl": crop_impl, "ocr_impl": ocr_impl,
        "correct_impl": correct_impl, "correct_params": correct_params,
        "translate_impl": translate_impl, "translate_params": translate_params,
        "do_translate": do_translate, "run_dir": run_dir, "slug": slug, "force": force,
    }

    # Aggregated in the main thread only (workers return data, never touch `result`).
    ok_rows: dict[int, tuple[str, list[dict]]] = {}      # n -> (page_id, rows)
    ok_translated: dict[int, str] = {}                   # n -> english
    total = len(pages)
    completed = 0
    successes = 0
    failures = 0
    stop = False  # set by credit exhaustion or the systemic circuit breaker

    def absorb(res: dict) -> None:
        """Fold one worker result into RunResult + print a progress line. Returns
        nothing; sets the outer `stop` flag via nonlocal on a halt condition."""
        nonlocal completed, successes, failures, stop, ocr_tag, correct_tag
        completed += 1
        n = res["n"]
        tag = f"[{completed}/{total}]"
        if res["status"] == "deferred":
            result.deferred.append({"page_id": res["page_id"], "reason": res["reason"]})
            print(f"  {tag} DEFER {res['page_id']}: {res['reason']}")
            return
        if res["status"] == "credit":
            result.credit_exhausted = True
            result.stopped_at = n
            result.failed.append({"n": n, "page_id": res["page_id"], "stage": res["stage"],
                                  "reason": f"credit/quota exhausted: {res['exc'][:160]}"})
            print(f"  {tag} ⛔ CREDIT EXHAUSTED at {res['page_id']} ({res['stage']}): {res['exc'][:120]}")
            stop = True
            return
        if res["status"] == "failed":
            failures += 1
            result.failed.append({"n": n, "page_id": res["page_id"], "stage": res["stage"],
                                  "reason": res["exc"][:200]})
            print(f"  {tag} FAIL {res['page_id']} ({res['stage']}): {res['exc'][:120]}")
            # Systemic guard: 3 failures with no success yet => broken setup (bad OCR
            # checkpoint, un-classified quota error). Halt before burning the book.
            if failures >= 3 and successes == 0:
                result.stopped_at = n
                print(f"  ⚠ {failures} failures and no successes — systemic problem, stopping.")
                stop = True
            return
        # ok
        successes += 1
        ocr_tag, correct_tag = res["ocr_tag"], res["correct_tag"]
        if res["score"]:
            result.scores.append(res["score"])
        if res["label_msg"]:
            result.needs_labeling.append(res["label_msg"])
        result.per_page[res["page_id"]] = res["page_path"]
        result.page_ids.append(res["page_id"])
        ok_rows[n] = (res["page_id"], res["rows"])
        if do_translate:
            result.translation_cost += res["cost"]
            result.translations[n] = res["tr_path"]
            ok_translated[n] = res["translation"]
            note = " (reused)" if res["tr_reused"] else f" (${res['cost']:.4f})"
            print(f"  {tag} OK {res['page_id']} -> {res['page_path'].name}{note}")
        else:
            print(f"  {tag} OK {res['page_id']} -> {res['page_path'].name}")

    if concurrency <= 1:
        for n in pages:
            absorb(_process_page(n, ctx))
            if stop:
                break
    else:
        # Bounded sliding window: at most `concurrency` pages in flight, submitted in
        # page order. On a halt we stop submitting; in-flight pages finish (their
        # on-disk caches persist, so a resume reuses them) but are not absorbed.
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

        it = iter(pages)
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            inflight = {}
            for _ in range(concurrency):
                n = next(it, None)
                if n is None:
                    break
                inflight[ex.submit(_process_page, n, ctx)] = n
            while inflight:
                done, _pending = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in done:
                    inflight.pop(fut)
                    absorb(fut.result())
                if stop:
                    break
                while len(inflight) < concurrency:
                    n = next(it, None)
                    if n is None:
                        break
                    inflight[ex.submit(_process_page, n, ctx)] = n

    # Rebuild every outward collection in PAGE order from the page-keyed aggregation
    # (workers complete out of order under concurrency; the docs + metadata must not).
    pages_rows = [ok_rows[n] for n in pages if n in ok_rows]
    pages_translated = [(n, ok_translated[n]) for n in pages if n in ok_translated]
    result.page_ids = [ok_rows[n][0] for n in pages if n in ok_rows]
    result.per_page = {pid: result.per_page[pid] for pid, _ in
                       ((ok_rows[n][0], n) for n in pages if n in ok_rows)}
    result.translations = {n: result.translations[n] for n in pages if n in result.translations}

    result.merged_doc = artifacts.write_merged_doc(run_dir, pages_rows)
    if do_translate and pages_translated:
        result.translated_doc = artifacts.write_translated_doc(
            run_dir, translate_impl.slug, pages_translated
        )
    result.worklist = artifacts.write_worklist(
        run_dir, result.deferred, result.needs_labeling, result.failed
    )
    if result.scores:
        json_path, _ = artifacts.write_scorecard(run_dir, result.scores)
        result.scorecard = json_path

    manifest = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "config_slug": slug,
        "config": {
            "crop": {"impl": config.crop.impl, "slug": crop_impl.slug, "doc": crop_impl.doc, "params": config.crop.params},
            "slice": {"impl": config.slice.impl, "slug": slice_impl.slug, "doc": slice_impl.doc},
            "ocr": {"impl": config.ocr.impl, "slug": ocr_impl.slug, "doc": ocr_impl.doc, "tag": ocr_tag},
            "correct": {"impl": config.correct.impl, "slug": correct_impl.slug, "doc": correct_impl.doc,
                        "tag": correct_tag, "params": correct_params},
            "translate": {"impl": translate, "slug": translate_impl.slug, "doc": translate_impl.doc,
                          "params": translate_params},
        },
        "translation_cost": round(result.translation_cost, 6) if do_translate else None,
        "pages": list(pages),
        "page_ids": result.page_ids,
        "deferred": result.deferred,
        "needs_labeling": result.needs_labeling,
        "failed": result.failed,
        "credit_exhausted": result.credit_exhausted,
        "stopped_at": result.stopped_at,
        "scored": bool(result.scores),
        "overall_cer": (
            round(sum(s["cer"] * s["n_scored"] for s in result.scores)
                  / sum(s["n_scored"] for s in result.scores), 4)
            if result.scores else None
        ),
    }
    artifacts.write_run_json(run_dir, manifest)
    return result
