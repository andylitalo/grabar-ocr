"""
Corpus promotion — consolidate blessed runs into the committed ``corpus/`` deliverable.

``pipeline/`` is the prototyping surface: every run lands in ``runs/<config-slug>/``
(gitignored, one folder per stage-choice combination) and the finished book is split
across several of them. This module **promotes** one or more blessed runs into a single,
canonical, page-keyed ``corpus/`` tree that *is* committed and that downstream services
consume:

  corpus/
    manifest.json              book index: page range, source-run config, per-page row, gaps
    book.grabar.md             all Grabar, "## <page_id>" headers, page order
    book.english.md            all English, "## <page_id>" headers, page order
    pages/page_NNNN.md         per-page: frontmatter + "## Grabar" + "## English"
    pages/page_NNNN.lines.json per-line Grabar + provenance pointers + page English

It is a **pure consolidator** in the spirit of ``pipeline/artifacts.py``: it reads existing
run artifacts and joins the committed region geometry (``data/columns/boxes/*.json`` via
``labeling_ui.storage``). It never re-runs a stage or re-spends tokens.

Traceability is pointer-based (images themselves stay gitignored): each line carries the
relative repo paths to its region crop and line slice, the region bounding box, and the
source run + per-stage model tags. The chain is
``corpus/pages/*.lines.json`` → ``data/columns/<page_id>_<region>.png`` /
``data/lines/<page_id>/<region>/line_NNN.png`` → committed
``data/columns/boxes/<page_id>.json`` → ``data/_labeling_work/<page_id>/page_deskew.png``
→ ``data/pages/<n>.pdf``; the source ``run.json`` records the models at each hop.

Precedence: runs are applied in the order given, so a page present in a later run wins.
The default order lists the human-verified run last, so human-labeled pages beat the
fully-automatic ones on the pages they overlap.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from labeling_ui import storage
from pipeline.artifacts import _PAGE_NUM_RE

REPO = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO / "runs"
CORPUS_DIR = REPO / "corpus"

# Blessed runs, human last so human-verified boxes win on overlapping pages.
DEFAULT_RUNS = ["auto__proj__tess__gemini-min", "human__proj__tess__gemini-min"]
DEFAULT_TRANSLATOR = "gemini-flash"

_LINES_SUFFIX = ".lines.json"


def _rel(p: Path) -> str:
    """Repo-relative POSIX path string (portable provenance pointer)."""
    return p.relative_to(REPO).as_posix()


def _region_bboxes(page_id: str) -> dict[str, dict]:
    """Map each region key (``region_NN_<type>``) to its loose (max) pixel box.

    Reuses ``labeling_ui.storage.load_regions`` which normalises both the region
    schema and the legacy two-box schema, so the join works for auto and human pages.
    """
    data = storage.load_regions(page_id)
    if not data:
        return {}
    return {
        storage.region_dirname(r["order"], r["type"]): r["max"]
        for r in data["regions"]
    }


def _source_block(run_slug: str, cfg: dict) -> dict:
    """Compact per-stage provenance pulled from a run's resolved config."""
    correct_params = (cfg.get("correct", {}) or {}).get("params") or {}
    translate_params = (cfg.get("translate", {}) or {}).get("params") or {}
    return {
        "run_slug": run_slug,
        "crop": (cfg.get("crop", {}) or {}).get("slug"),
        "slice": (cfg.get("slice", {}) or {}).get("slug"),
        "ocr": {
            "impl": (cfg.get("ocr", {}) or {}).get("impl"),
            "tag": (cfg.get("ocr", {}) or {}).get("tag"),
        },
        "correct": {
            "model": correct_params.get("cli_model"),
            "mode": correct_params.get("mode"),
        },
        "translate": {"model": translate_params.get("cli_model")},
    }


def build_page_record(
    run_dir: Path,
    run_slug: str,
    cfg: dict,
    page_num: int,
    page_id: str,
    translator: str,
) -> dict:
    """Enriched, self-describing per-page record (superset of the run lines.json)."""
    raw = json.loads((run_dir / "pages" / f"{page_id}{_LINES_SUFFIX}").read_text("utf-8"))
    bboxes = _region_bboxes(page_id)

    lines = []
    for ln in raw["lines"]:
        region = ln["region"]
        line_id = ln["line_id"]
        lines.append(
            {
                "index": ln["index"],
                "line_id": line_id,
                "region": region,
                "column": ln.get("column"),
                "non_character": ln["non_character"],
                "ocr_raw": ln.get("ocr_beam"),
                "grabar": ln.get("corrected"),
                "region_bbox": bboxes.get(region),
                "crop_image": _rel(storage.DATA_COLUMNS / f"{page_id}_{region}.png"),
                "line_image": _rel(storage.DATA_LINES / page_id / f"{line_id}.png"),
            }
        )

    english_path = run_dir / "translations" / translator / f"page_{page_num}.txt"
    english = english_path.read_text("utf-8").rstrip("\n") if english_path.exists() else None

    return {
        "page": page_num,
        "page_id": page_id,
        "source": _source_block(run_slug, cfg),
        "provenance": {
            "source_pdf": _rel(storage.page_pdf_path(page_num)),
            "deskew_render": _rel(
                storage.WORK_DIR / storage.page_id_for(page_num) / "page_deskew.png"
            ),
            "region_boxes": _rel(storage.boxes_path(page_id)),
        },
        "cer": raw.get("cer"),
        "counts": raw.get("counts"),
        "english": english,
        "lines": lines,
    }


def build_blank_record(page_num: int) -> dict:
    """Explicit corpus record for a page marked blank in the labeling UI.

    Blankness is the single source of truth (``data/pages/blank/page_XXXX.json`` via
    ``storage.is_blank``); a blank page has no crop, no lines and no translation, so it
    is promoted as a first-class ``blank: true`` page (not a gap). Keyed by the base
    page id, since blankness is a property of the source page.
    """
    marker = json.loads(storage.blank_marker_path(page_num).read_text("utf-8"))
    return {
        "page": page_num,
        "page_id": storage.page_id_for(page_num),
        "blank": True,
        "source": {"blank_marked_by": marker.get("marked_by", "human")},
        "provenance": {
            "source_pdf": _rel(storage.page_pdf_path(page_num)),
            "blank_marker": _rel(storage.blank_marker_path(page_num)),
        },
        "cer": None,
        "counts": {"total": 0, "text": 0, "non_character": 0, "labeled": 0},
        "english": None,
        "lines": [],
    }


def _text_line_count(record: dict) -> int:
    counts = record.get("counts") or {}
    if "text" in counts:
        return counts["text"]
    return sum(1 for ln in record["lines"] if not ln["non_character"])


_BLANK_MARKER = "_(blank page — no text in the source)_"


def _page_md(record: dict) -> str:
    """Per-page markdown: frontmatter + Grabar (reading order) + English prose."""
    if record.get("blank"):
        front = [
            "---",
            f"page: {record['page']}",
            f"page_id: {record['page_id']}",
            "blank: true",
            f"blank_marked_by: {record['source'].get('blank_marked_by', 'human')}",
            "---",
        ]
        body = ["", f"# Page {record['page']}", "", _BLANK_MARKER]
        return "\n".join(front + body) + "\n"

    s = record["source"]
    front = [
        "---",
        f"page: {record['page']}",
        f"page_id: {record['page_id']}",
        f"source_run: {s['run_slug']}",
        f"ocr: {s['ocr']['tag']}",
        f"correct: {s['correct']['model']}/{s['correct']['mode']}",
        f"translate: {s['translate']['model']}",
        f"lines: {_text_line_count(record)}",
        f"cer: {record['cer']}",
        "---",
    ]
    grabar = "\n".join(
        ln["grabar"] for ln in record["lines"] if not ln["non_character"]
    )
    english = record["english"] or "_No translation available._"
    body = [
        "",
        f"# Page {record['page']}",
        "",
        "## Grabar",
        "",
        grabar,
        "",
        "## English",
        "",
        english,
    ]
    return "\n".join(front + body) + "\n"


def write_page_artifacts(out_dir: Path, record: dict) -> tuple[Path, Path]:
    """Write ``pages/page_NNNN.lines.json`` and ``pages/page_NNNN.md`` for one page."""
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    stem = f"page_{record['page']:04d}"
    json_path = pages_dir / f"{stem}{_LINES_SUFFIX}"
    md_path = pages_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    md_path.write_text(_page_md(record), "utf-8")
    return json_path, md_path


def _load_corpus_pages(out_dir: Path) -> list[dict]:
    """Every promoted per-page record on disk, in page-number order."""
    pages_dir = out_dir / "pages"
    recs: list[dict] = []
    if pages_dir.is_dir():
        for p in pages_dir.glob(f"*{_LINES_SUFFIX}"):
            recs.append(json.loads(p.read_text("utf-8")))
    recs.sort(key=lambda r: r["page"])
    return recs


def rebuild_book_docs(out_dir: Path, recs: list[dict]) -> tuple[Path, Path]:
    """Rebuild ``book.grabar.md`` / ``book.english.md`` from all pages on disk.

    Mirrors ``artifacts.rebuild_merged_doc_from_disk`` so incremental promotions
    accumulate instead of clobbering. ``## <page_id>`` headers, page-number order.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    grabar_blocks, english_blocks = [], []
    for r in recs:
        pid = r["page_id"]
        if r.get("blank"):
            grabar_blocks.append(f"## {pid}\n\n{_BLANK_MARKER}")
            english_blocks.append(f"## {pid}\n\n{_BLANK_MARKER}")
            continue
        grabar = "\n".join(
            ln["grabar"] for ln in r["lines"] if not ln["non_character"]
        )
        grabar_blocks.append(f"## {pid}\n\n{grabar}")
        english = r.get("english") or "_No translation available._"
        english_blocks.append(f"## {pid}\n\n{english}")
    g_path = out_dir / "book.grabar.md"
    e_path = out_dir / "book.english.md"
    g_path.write_text("\n\n".join(grabar_blocks) + "\n", "utf-8")
    e_path.write_text("\n\n".join(english_blocks) + "\n", "utf-8")
    return g_path, e_path


def write_manifest(
    out_dir: Path,
    recs: list[dict],
    source_runs: list[dict],
    gaps: list[dict],
    page_range: list[int],
) -> Path:
    """The book index: coverage, per-run config, per-page rows, and known gaps."""
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "page_range": page_range,
        "source_runs": source_runs,
        "n_pages": len(recs),
        "n_blank": sum(1 for r in recs if r.get("blank")),
        "pages": [
            {
                "page": r["page"],
                "page_id": r["page_id"],
                "source_run": r["source"].get("run_slug") if not r.get("blank") else None,
                "blank": bool(r.get("blank")),
                "n_lines": _text_line_count(r),
                "has_translation": r["english"] is not None,
                "cer": r["cer"],
            }
            for r in recs
        ],
        "gaps": gaps,
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return path


def _index_run(run_dir: Path) -> tuple[dict, dict[int, str]]:
    """(resolved config, {page_num: page_id}) for one run folder."""
    manifest = json.loads((run_dir / "run.json").read_text("utf-8"))
    index: dict[int, str] = {}
    pages_dir = run_dir / "pages"
    if pages_dir.is_dir():
        for p in pages_dir.glob(f"*{_LINES_SUFFIX}"):
            page_id = p.name[: -len(_LINES_SUFFIX)]
            m = _PAGE_NUM_RE.search(page_id)
            if m:
                index[int(m.group(1))] = page_id
    return manifest, index


def promote(
    run_slugs: list[str],
    lo: int,
    hi: int,
    translator: str = DEFAULT_TRANSLATOR,
    out_dir: Path = CORPUS_DIR,
) -> dict:
    """Promote the blessed runs' pages in [lo, hi] into ``out_dir``.

    Later runs in ``run_slugs`` win on overlapping pages. Returns a summary dict.
    """
    chosen: dict[int, tuple[str, Path, dict, str]] = {}  # page_num -> (slug, dir, cfg, page_id)
    deferred_reasons: dict[int, str] = {}
    source_runs: list[dict] = []

    for slug in run_slugs:
        run_dir = RUNS_DIR / slug
        manifest, index = _index_run(run_dir)
        cfg = manifest["config"]
        source_runs.append({"slug": slug, "config": _source_block(slug, cfg)})
        for d in manifest.get("deferred", []):
            m = _PAGE_NUM_RE.search(d["page_id"])
            if m:
                deferred_reasons.setdefault(int(m.group(1)), d["reason"])
        for n, page_id in index.items():
            if lo <= n <= hi:
                chosen[n] = (slug, run_dir, cfg, page_id)  # later run wins

    # A page marked blank in the labeling UI is promoted as an explicit blank page and
    # never as digitized content, even if a (mis-detected) run artifact exists for it —
    # the blank marker is the single source of truth.
    blanks = [n for n in range(lo, hi + 1) if storage.is_blank(n)]
    blank_set = set(blanks)

    for n, (slug, run_dir, cfg, page_id) in sorted(chosen.items()):
        if n in blank_set:
            continue
        record = build_page_record(run_dir, slug, cfg, n, page_id, translator)
        write_page_artifacts(out_dir, record)

    for n in blanks:
        write_page_artifacts(out_dir, build_blank_record(n))

    recs = _load_corpus_pages(out_dir)
    on_disk = {r["page"] for r in recs}
    gaps = [
        {"page": n, "reason": deferred_reasons.get(n, "no output in any source run")}
        for n in range(lo, hi + 1)
        if n not in on_disk
    ]

    rebuild_book_docs(out_dir, recs)
    write_manifest(out_dir, recs, source_runs, gaps, [lo, hi])

    return {
        "on_disk": len(recs),
        "content": sum(1 for r in recs if not r.get("blank")),
        "blank": len(blanks),
        "gaps": gaps,
        "with_translation": sum(1 for r in recs if r["english"] is not None),
    }


def _parse_range(spec: str) -> tuple[int, int]:
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return int(lo), int(hi)
    n = int(spec)
    return n, n


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="pipeline.promote",
        description="Promote blessed runs into the committed corpus/ deliverable.",
    )
    ap.add_argument("--range", required=True, help="page range, e.g. 458-641 or 458")
    ap.add_argument(
        "--from",
        dest="runs",
        nargs="+",
        default=DEFAULT_RUNS,
        help="run slugs, applied in order (later wins on overlap)",
    )
    ap.add_argument("--translator", default=DEFAULT_TRANSLATOR)
    ap.add_argument("--out", default=str(CORPUS_DIR), type=Path)
    args = ap.parse_args(argv)

    lo, hi = _parse_range(args.range)
    summary = promote(args.runs, lo, hi, args.translator, Path(args.out))
    print(
        f"corpus: {summary['on_disk']} pages on disk "
        f"({summary['content']} content, {summary['blank']} blank, "
        f"{summary['with_translation']} with English), "
        f"{len(summary['gaps'])} gap(s) in {lo}-{hi}"
    )
    if summary["gaps"]:
        for g in summary["gaps"]:
            print(f"  gap page {g['page']}: {g['reason']}")


if __name__ == "__main__":
    main()
