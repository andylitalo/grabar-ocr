"""
storage.py
Filesystem layer for the labeling tool.

Single source of truth for on-disk paths and label state. Knows the
`data/lines/page_XXXX_<method>/region_NN_<type>/line_NNN.{png,txt}` convention
(method in {human, auto}; type in {header, single, left, right} — see
page_artifact_id, region_dirname and data/README.md), the `rejected/` subdir, and
the rules that map files to a line's status. Legacy `column_N` line dirs are still
read (back-compat); data_prep.migrate_region_names renames them. No FastAPI
imports — pure functions, independently testable.

Status model (computed purely from the filesystem):
  - PNG under column_Y/rejected/          -> "rejected"
  - PNG + sibling .txt with non-empty text -> "labeled"
  - PNG + sibling .txt empty/whitespace    -> "empty"   (valid section marker)
  - PNG with no sibling .txt               -> "pending" (not yet labeled)
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from jiwer import cer

REPO = Path(__file__).resolve().parents[1]
DATA_PAGES = REPO / "data" / "pages"
DATA_COLUMNS = REPO / "data" / "columns"
DATA_COLUMN_BOXES = DATA_COLUMNS / "boxes"
DATA_LINES = REPO / "data" / "lines"
DATA_PREDICTIONS = REPO / "data" / "predictions"
WORK_DIR = REPO / "data" / "_labeling_work"

# Which offline prediction set the Review view reads. Predictions are written by
# ml_vision/scripts/predict_lines.py into data/predictions/<tag>/page_XXXX/. The
# app NEVER runs the model — it only reads these files.
DEFAULT_MODEL_TAG = os.environ.get("GRABAR_MODEL_TAG", "scale_500")

# Page source files are named "{n}.pdf" (see cut_pdf.py).
_PAGE_PDF_RE = re.compile(r"^(\d+)\.pdf$")


def page_id_for(n: int) -> str:
    """Canonical page id for page number n, e.g. 543 -> 'page_0543'.

    This is the *base* page id, keyed only by page number. It is used for the
    method-independent render cache (the deskewed page is the same regardless of
    who draws the column boxes). Derived per-method artifacts (columns, lines,
    boxes, predictions) live under the method-tagged id from ``page_artifact_id``.
    """
    return f"page_{n:04d}"


# Method tag for derived line/column/box/prediction artifacts. "human" = produced
# through the labeling UI (a person drew/accepted the boxes); "auto" = produced by
# the headless detector (data_prep.auto_slice). The tag rides on the page id so it
# propagates through the whole tree, e.g. page_0487_auto. See data/README.md.
METHOD_HUMAN = "human"
METHOD_AUTO = "auto"


def page_artifact_id(n: int, method: str = METHOD_HUMAN) -> str:
    """Method-tagged page id for derived artifacts, e.g. (487, 'auto') -> 'page_0487_auto'.

    Columns (data/columns/<id>_column_Y.png), line dirs (data/lines/<id>/),
    column boxes (data/columns/boxes/<id>.json), and predictions
    (data/predictions/<tag>/<id>/) are all keyed by this id, so auto and human
    runs of the same page coexist instead of overwriting each other.
    """
    return f"{page_id_for(n)}_{method}"


def page_pdf_path(n: int) -> Path:
    """Source one-page PDF for page number n."""
    return DATA_PAGES / f"{n}.pdf"


# --- region identity (Phase 6) -----------------------------------------------
#
# A page is an ordered list of typed regions, each a line-crop directory named
# ``region_NN_<type>`` (NN = 2-digit reading order; type in REGION_TYPES). The
# directory name *is* the region key; every line-id is ``<region_key>/line_NNN``,
# derived from the actual on-disk dir, so keys stay correct whether a page has
# migrated region dirs or legacy ``column_N`` dirs. Reading order = NN ascending;
# within a two-column band, ``left`` (smaller NN) before ``right``.
#
# Back-compat: ``column_1`` reads as ``(1, "left")``, ``column_2`` as
# ``(2, "right")``; the one-shot data_prep.migrate_region_names renames the dirs
# and repoints stored prediction/truth keys so both halves stay in sync.

REGION_TYPES = ("header", "single", "left", "right")

_REGION_DIR_RE = re.compile(r"^region_(\d{2})_(header|single|left|right)$")
_LEGACY_COL_RE = re.compile(r"^column_(\d+)$")


def region_dirname(order: int, rtype: str) -> str:
    """Directory/region key for a region, e.g. (1, 'left') -> 'region_01_left'."""
    if rtype not in REGION_TYPES:
        raise ValueError(f"Unknown region type: {rtype!r}")
    return f"region_{order:02d}_{rtype}"


def parse_region(dirname: str) -> tuple[int, str] | None:
    """(order, type) for a region or legacy column dir name, or None if neither."""
    m = _REGION_DIR_RE.match(dirname)
    if m:
        return int(m.group(1)), m.group(2)
    m = _LEGACY_COL_RE.match(dirname)
    if m:
        col = int(m.group(1))
        return col, ("left" if col == 1 else "right" if col == 2 else "single")
    return None


def region_dir(page_id: str, region: str) -> Path:
    """Line-crop directory for a region key (``region_NN_<type>`` or ``column_N``)."""
    return DATA_LINES / page_id / region


def region_dirs_in(page_dir: Path) -> list[Path]:
    """Region/column line-crop dirs under a page dir, in reading order (NN ascending).

    Path-based sibling of ``list_region_dirs`` so data_prep scripts that work on an
    arbitrary lines dir share the one ordering/back-compat rule (region_* then any
    legacy column_*). The single source for global line reading order.
    """
    if not page_dir.is_dir():
        return []
    dirs = [d for d in page_dir.iterdir() if d.is_dir() and parse_region(d.name)]
    return sorted(dirs, key=lambda d: (parse_region(d.name)[0], d.name))


def list_region_dirs(page_id: str) -> list[Path]:
    """Region/column line-crop dirs for a page id, in reading order (NN ascending)."""
    return region_dirs_in(DATA_LINES / page_id)


def line_id_for(region: str, line: int) -> str:
    """Canonical line-id: ``<region_key>/line_NNN`` (e.g. 'region_01_left/line_007')."""
    return f"{region}/line_{line:03d}"


def column_dir(page_id: str, col: int) -> Path:
    """Back-compat shim: legacy ``column_N`` line dir (pre-region naming)."""
    return DATA_LINES / page_id / f"column_{col}"


# --- column bounding boxes (geometric ground truth) --------------------------


def boxes_path(page_id: str) -> Path:
    """Persisted column boxes for a page, e.g. data/columns/boxes/page_0051.json."""
    return DATA_COLUMN_BOXES / f"{page_id}.json"


def save_boxes(
    page_id: str, deskew_angle: float, boxes: list[dict], source: str = "human"
) -> Path:
    """Persist the column boxes (full-res pixels) and the page's deskew angle.

    ``source`` is "human" when committed through the labeling UI (a human accepted
    the boxes) or "auto" when written by the headless detector. Only human-sourced
    boxes are geometric ground truth; validation computes IoU against those alone,
    never against the detector's own output.
    """
    DATA_COLUMN_BOXES.mkdir(parents=True, exist_ok=True)
    path = boxes_path(page_id)
    # Never let an auto-written box overwrite a human-verified one.
    if source == "auto":
        existing = load_boxes(page_id)
        if existing and existing.get("source") == "human":
            return path
    payload = {
        "page_id": page_id,
        "source": source,
        "deskew_angle": deskew_angle,
        "boxes": [{k: int(b[k]) for k in ("x1", "y1", "x2", "y2")} for b in boxes],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def save_regions(
    page_id: str, deskew_angle: float, regions: list[dict], source: str = "human"
) -> Path:
    """Persist the typed region ground truth (min + max boxes) and deskew angle.

    ``regions`` is an ordered list of ``{"type", "min", "max"}`` where ``min`` is
    the tight inner box (must contain all real text) and ``max`` is the loose outer
    box (just inside the frame / central divider / margin). The detector passes
    gate #4 when ``min ⊆ detected ⊆ max`` for each region. ``deskew_angle`` is the
    human reference-line angle (gate #6 ground truth). Order rides on list order.
    Never lets an auto write clobber a human-verified file (same rule as save_boxes).
    """
    DATA_COLUMN_BOXES.mkdir(parents=True, exist_ok=True)
    path = boxes_path(page_id)
    if source == "auto":
        existing = load_boxes(page_id)
        if existing and existing.get("source") == "human":
            return path

    def _rect(b: dict) -> dict:
        return {k: int(b[k]) for k in ("x1", "y1", "x2", "y2")}

    payload = {
        "page_id": page_id,
        "source": source,
        "deskew_angle": float(deskew_angle),
        "regions": [
            {"order": i, "type": r["type"], "min": _rect(r["min"]), "max": _rect(r["max"])}
            for i, r in enumerate(regions, start=1)
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_boxes(page_id: str) -> dict | None:
    """Load the persisted geometry for a page (region or legacy box schema), or None."""
    path = boxes_path(page_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_regions(page_id: str) -> dict | None:
    """Persisted geometry normalised to the region schema, or None if not recorded.

    Region-schema files pass through. A legacy two-box file is adapted into
    ``left``/``right`` regions with ``min == max == box`` so old annotations stay
    readable (back-compat shim).
    """
    data = load_boxes(page_id)
    if data is None:
        return None
    if "regions" in data:
        return data
    boxes = data.get("boxes", [])
    types = ["left", "right"] if len(boxes) == 2 else ["single"] * len(boxes)
    regions = [
        {"order": i, "type": t, "min": dict(b), "max": dict(b)}
        for i, (t, b) in enumerate(zip(types, boxes), start=1)
    ]
    return {
        "page_id": data.get("page_id", page_id),
        "source": data.get("source", "human"),
        "deskew_angle": data.get("deskew_angle", 0.0),
        "regions": regions,
    }


def list_page_numbers() -> list[int]:
    """All page numbers available in data/pages/, sorted ascending."""
    if not DATA_PAGES.is_dir():
        return []
    numbers: list[int] = []
    for entry in DATA_PAGES.iterdir():
        m = _PAGE_PDF_RE.match(entry.name)
        if m:
            numbers.append(int(m.group(1)))
    return sorted(numbers)


def line_status(col_dir: Path, line: int) -> str:
    """Status of a single line within a column dir."""
    stem = f"line_{line:03d}"
    rejected_png = col_dir / "rejected" / f"{stem}.png"
    if rejected_png.exists():
        return "rejected"
    txt = col_dir / f"{stem}.txt"
    if not txt.exists():
        return "pending"
    return "labeled" if txt.read_text(encoding="utf-8").strip() else "empty"


def line_text(col_dir: Path, line: int) -> str:
    """Stored text for a line (empty string if none / rejected)."""
    txt = col_dir / f"line_{line:03d}.txt"
    if txt.exists():
        return txt.read_text(encoding="utf-8")
    return ""


def _line_numbers(col_dir: Path) -> list[int]:
    """Line indices present in a column (counting both placed and rejected PNGs)."""
    numbers: set[int] = set()
    for png in col_dir.glob("line_*.png"):
        numbers.add(int(png.stem.split("_")[1]))
    rejected = col_dir / "rejected"
    if rejected.is_dir():
        for png in rejected.glob("line_*.png"):
            numbers.add(int(png.stem.split("_")[1]))
    return sorted(numbers)


def page_predictions(page_id: str, model_tag: str = DEFAULT_MODEL_TAG) -> tuple[str | None, dict]:
    """(model_tag, {'<region_key>/line_NNN': pred_text}) read from data/predictions/.

    Prefers the configured tag; falls back to any tag dir that has predictions
    for this page. Returns (None, {}) when no prediction set exists — the app
    then simply shows no predictions (it never runs the model itself).
    """
    candidates = [DATA_PREDICTIONS / model_tag]
    if DATA_PREDICTIONS.is_dir():
        candidates += [d for d in sorted(DATA_PREDICTIONS.iterdir()) if d.name != model_tag]
    for tag_dir in candidates:
        pred_json = tag_dir / page_id / "predictions.json"
        if pred_json.exists():
            data = json.loads(pred_json.read_text(encoding="utf-8"))
            # Beam is the headline prediction (see predict_lines.py).
            preds = {lid: v.get("pred_beam", "") for lid, v in data["lines"].items()}
            return tag_dir.name, preds
    return None, {}


def line_prediction(page_id: str, region: str, line: int, model_tag: str = DEFAULT_MODEL_TAG) -> str | None:
    """Stored prediction for one line, or None if no prediction set covers it."""
    _, preds = page_predictions(page_id, model_tag)
    return preds.get(line_id_for(region, line))


def list_lines(page_id: str) -> dict:
    """Flat, ordered list of all lines across regions, with status + text.

    The flat order (region_01 lines, then region_02, ...) is the global reading
    order and matches what `build_phase4_dataset.flatten_columns` uses.

    Each line carries its canonical `line_id` (``<region_key>/line_NNN``), the
    `region` dir name and `region_type`. When an offline prediction set exists
    (data/predictions/<tag>/), each line also carries `pred` and, for labeled
    lines, its `cer` against the stored text. The app never runs the model.
    """
    page_dir = DATA_LINES / page_id
    lines: list[dict] = []
    counts = {"labeled": 0, "empty": 0, "rejected": 0, "pending": 0}
    model_tag, preds = page_predictions(page_id)

    if page_dir.is_dir():
        for region_path in list_region_dirs(page_id):
            region = region_path.name
            order, rtype = parse_region(region)
            for line in _line_numbers(region_path):
                status = line_status(region_path, line)
                counts[status] += 1
                text = line_text(region_path, line)
                lid = line_id_for(region, line)
                pred = preds.get(lid)
                line_cer = (
                    cer(text.strip(), pred)
                    if pred is not None and status == "labeled" and text.strip()
                    else None
                )
                lines.append(
                    {
                        "index": len(lines),
                        "region": region,
                        "region_type": rtype,
                        "column": order,
                        "line": line,
                        "line_id": lid,
                        "status": status,
                        "text": text,
                        "pred": pred,
                        "cer": line_cer,
                        "image_url": (
                            f"/api/page/{page_id}/region/{region}/line/{line}/image"
                        ),
                    }
                )

    counts["total"] = len(lines)
    return {"page_id": page_id, "lines": lines, "counts": counts, "model_tag": model_tag}


# --- non-character truth artifact (Phase A detector validation) --------------
#
# To measure the pre-OCR non-character detector's recall on production-like auto
# pages, a human gives a binary verdict on EVERY line of a sampled auto page. The
# verdicts plus the detector's snapshotted prediction land in one JSON file beside
# the page's column_*/ dirs. A dedicated file (not an empty .txt) is required: a
# "character" line has no transcription, so an empty .txt would be ambiguous with
# the "empty" verdict. This module stays cv2-free — image features are passed in.


def nonchar_truth_path(page_id: str) -> Path:
    """Truth artifact for a page, e.g. data/lines/page_0123_auto/nonchar_truth.json."""
    return DATA_LINES / page_id / "nonchar_truth.json"


def load_nonchar_truth(page_id: str) -> dict | None:
    """Load the saved non-character truth for a page, or None if not verified."""
    path = nonchar_truth_path(page_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_nonchar_truth(
    page_id: str,
    verdicts: dict[str, str],
    detector_meta: dict,
    line_features: dict[str, dict],
) -> Path:
    """Write the human verdicts + detector snapshot for a verified auto page.

    ``verdicts`` maps "column_Y/line_NNN" -> "empty" | "character" (the human's
    source of truth). ``line_features`` maps the same line ids to the detector's
    snapshot ``{non_character, glyph_count, ink_ratio}`` so scoring is reproducible
    and threshold drift is visible. ``detector_meta`` records the rule used.
    """
    from datetime import datetime, timezone

    lines: dict[str, dict] = {}
    for line_id, truth in verdicts.items():
        feat = line_features.get(line_id, {})
        lines[line_id] = {
            "truth": truth,
            "detector_nonchar": bool(feat.get("non_character", False)),
            "glyph_count": feat.get("glyph_count"),
            "ink_ratio": feat.get("ink_ratio"),
        }
    payload = {
        "page_id": page_id,
        "verified_by": "human",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "detector": detector_meta,
        "lines": lines,
    }
    path = nonchar_truth_path(page_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def has_auto_lines(n: int) -> bool:
    """True if page n has any auto-sliced line crops (page_XXXX_auto/<region>/)."""
    auto_id = page_artifact_id(n, METHOD_AUTO)
    return any(any(d.glob("line_*.png")) for d in list_region_dirs(auto_id))


def nonchar_verified(page_id: str) -> bool:
    """True if a non-character truth file has been saved for this page."""
    return nonchar_truth_path(page_id).exists()


def auto_status(n: int) -> str:
    """Auto-tree status for the page browser: none / sliced / verified."""
    if not has_auto_lines(n):
        return "none"
    return "verified" if nonchar_verified(page_artifact_id(n, METHOD_AUTO)) else "sliced"


def page_status(page_id: str) -> str:
    """Coarse page status for the page browser: unlabeled / in_progress / done."""
    info = list_lines(page_id)
    counts = info["counts"]
    if counts["total"] == 0:
        return "unlabeled"
    if counts["pending"] > 0:
        return "in_progress"
    return "done"


def page_has_labels(page_id: str) -> bool:
    """True if any region of the page already holds a labeled/empty .txt (re-crop guard)."""
    return any(any(d.glob("line_*.txt")) for d in list_region_dirs(page_id))


def column_has_labels(page_id: str, col: int) -> bool:
    """Back-compat: True if legacy column ``col`` holds any labeled/empty .txt."""
    col_dir = column_dir(page_id, col)
    if not col_dir.is_dir():
        return False
    return any(col_dir.glob("line_*.txt"))


def line_image_path(page_id: str, region: str, line: int) -> Path | None:
    """Path to a line's PNG, whether placed or rejected; None if absent."""
    rdir = region_dir(page_id, region)
    stem = f"line_{line:03d}.png"
    placed = rdir / stem
    if placed.exists():
        return placed
    rejected = rdir / "rejected" / stem
    if rejected.exists():
        return rejected
    return None


# --- label mutations ---------------------------------------------------------


def _unreject(col_dir: Path, line: int) -> None:
    """Move a rejected PNG back into its canonical slot, if rejected."""
    stem = f"line_{line:03d}.png"
    rejected_png = col_dir / "rejected" / stem
    if rejected_png.exists():
        shutil.move(str(rejected_png), str(col_dir / stem))


def apply_label(page_id: str, region: str, line: int, action: str, text: str = "") -> dict:
    """Mutate the filesystem to reflect a label action; return new status + text.

    action ∈ {"submit", "empty", "reject"}. Every action first un-rejects so
    state transitions out of "rejected" are automatic and self-cleaning.
    """
    rdir = region_dir(page_id, region)
    stem = f"line_{line:03d}"
    txt = rdir / f"{stem}.txt"

    if action == "reject":
        rejected_dir = rdir / "rejected"
        rejected_dir.mkdir(parents=True, exist_ok=True)
        png = rdir / f"{stem}.png"
        if png.exists():
            shutil.move(str(png), str(rejected_dir / f"{stem}.png"))
        txt.unlink(missing_ok=True)
        return {"status": "rejected", "text": ""}

    _unreject(rdir, line)

    if action == "submit":
        txt.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
        return {"status": line_status(rdir, line), "text": line_text(rdir, line)}

    if action == "empty":
        txt.write_text("", encoding="utf-8")
        return {"status": "empty", "text": ""}

    raise ValueError(f"Unknown action: {action!r}")
