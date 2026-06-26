"""
Run-artifact writers.

A run lands in ``runs/<config-slug>/`` (gitignored — derived output). Contents:

  run.json                       resolved config + per-stage docs + tags + status
  pages/<page_id>.lines.json     per-line OCR/corrected text (+ ref/cer if scored)
  merged.md                      every text line, all pages, reading order — the
                                 single document handed downstream to translation
  scorecard.json / scorecard.md  written ONLY when at least one page has ground truth

These are pure writers: they receive already-collected rows (see
orchestrator.collect_rows) and never run a stage.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO / "runs"


def _counts(rows: list[dict]) -> dict:
    text = sum(1 for r in rows if not r["non_character"])
    return {
        "total": len(rows),
        "text": text,
        "non_character": len(rows) - text,
        "labeled": sum(1 for r in rows if r["ref"] is not None),
    }


def write_lines_json(
    run_dir: Path,
    page_id: str,
    rows: list[dict],
    *,
    config_slug: str,
    ocr_tag: str,
    correct_tag: str,
    score: dict | None,
) -> Path:
    """Per-line JSON for one page (join of baseline OCR + corrected + optional ref/cer)."""
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "page_id": page_id,
        "config_slug": config_slug,
        "ocr_tag": ocr_tag,
        "correct_tag": correct_tag,
        "cer": score["cer"] if score else None,
        "counts": _counts(rows),
        "lines": rows,
    }
    out = pages_dir / f"{page_id}.lines.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def write_merged_doc(run_dir: Path, pages_rows: list[tuple[str, list[dict]]]) -> Path:
    """Combined document: all text lines from all pages, reading order, per-page headers.

    Non-character lines are excluded (exactly like digitize_page.write_outputs), so
    the file is ready to feed to a translation LLM.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for page_id, rows in pages_rows:
        text_lines = [r["corrected"] for r in rows if not r["non_character"]]
        blocks.append(f"## {page_id}\n\n" + "\n".join(text_lines))
    out = run_dir / "merged.md"
    out.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return out


def write_scorecard(run_dir: Path, scores: list[dict]) -> tuple[Path, Path]:
    """Per-page + overall CER as scorecard.json and a human-readable scorecard.md."""
    run_dir.mkdir(parents=True, exist_ok=True)
    n_total = sum(s["n_scored"] for s in scores)
    # Char-weighted overall CER would need the raw refs; approximate with the
    # line-count-weighted mean of per-page corpus CER (each page already corpus-level).
    overall = (
        sum(s["cer"] * s["n_scored"] for s in scores) / n_total if n_total else None
    )
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "overall_cer": round(overall, 4) if overall is not None else None,
        "n_scored": n_total,
        "pages": scores,
    }
    json_path = run_dir / "scorecard.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md = ["# CER scorecard", ""]
    md.append(f"Overall CER: **{overall:.4f}** ({n_total} lines scored)" if overall is not None else "No lines scored.")
    md.append("")
    md.append("| page | lines scored | CER |")
    md.append("| --- | ---: | ---: |")
    for s in scores:
        md.append(f"| {s['page_id']} | {s['n_scored']} | {s['cer']:.4f} |")
    md_path = run_dir / "scorecard.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return json_path, md_path


def write_run_json(run_dir: Path, manifest: dict) -> Path:
    """The run manifest: resolved config, stage docs, tags, pages, deferred, needs_labeling."""
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "run.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
