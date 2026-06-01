"""
storage.py
Filesystem layer for the labeling tool.

Single source of truth for on-disk paths and label state. Knows the
`data/lines/page_XXXX/column_Y/line_NNN.{png,txt}` convention, the `rejected/`
subdir, and the rules that map files to a line's status. No FastAPI imports —
pure functions, independently testable.

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
    """Canonical page id for page number n, e.g. 543 -> 'page_0543'."""
    return f"page_{n:04d}"


def page_pdf_path(n: int) -> Path:
    """Source one-page PDF for page number n."""
    return DATA_PAGES / f"{n}.pdf"


def column_dir(page_id: str, col: int) -> Path:
    return DATA_LINES / page_id / f"column_{col}"


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
    """(model_tag, {'column_Y/line_NNN': pred_text}) read from data/predictions/.

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


def line_prediction(page_id: str, col: int, line: int, model_tag: str = DEFAULT_MODEL_TAG) -> str | None:
    """Stored prediction for one line, or None if no prediction set covers it."""
    _, preds = page_predictions(page_id, model_tag)
    return preds.get(f"column_{col}/line_{line:03d}")


def list_lines(page_id: str) -> dict:
    """Flat, ordered list of all lines across columns, with status + text.

    The flat order (column_1 lines, then column_2, ...) matches the order
    `build_phase4_dataset.flatten_columns` will later use.

    When an offline prediction set exists for the page (data/predictions/<tag>/),
    each line also carries `pred` (the model's read-only prediction) and, for
    labeled lines, its `cer` against the stored text. The app never runs the model.
    """
    page_dir = DATA_LINES / page_id
    lines: list[dict] = []
    counts = {"labeled": 0, "empty": 0, "rejected": 0, "pending": 0}
    model_tag, preds = page_predictions(page_id)

    if page_dir.is_dir():
        for col_dir in sorted(page_dir.glob("column_*")):
            col = int(col_dir.name.split("_")[1])
            for line in _line_numbers(col_dir):
                status = line_status(col_dir, line)
                counts[status] += 1
                text = line_text(col_dir, line)
                pred = preds.get(f"column_{col}/line_{line:03d}")
                line_cer = (
                    cer(text.strip(), pred)
                    if pred is not None and status == "labeled" and text.strip()
                    else None
                )
                lines.append(
                    {
                        "index": len(lines),
                        "column": col,
                        "line": line,
                        "status": status,
                        "text": text,
                        "pred": pred,
                        "cer": line_cer,
                        "image_url": (
                            f"/api/page/{page_id}/column/{col}/line/{line}/image"
                        ),
                    }
                )

    counts["total"] = len(lines)
    return {"page_id": page_id, "lines": lines, "counts": counts, "model_tag": model_tag}


def page_status(page_id: str) -> str:
    """Coarse page status for the page browser: unlabeled / in_progress / done."""
    info = list_lines(page_id)
    counts = info["counts"]
    if counts["total"] == 0:
        return "unlabeled"
    if counts["pending"] > 0:
        return "in_progress"
    return "done"


def column_has_labels(page_id: str, col: int) -> bool:
    """True if the column already holds any labeled/empty .txt (re-crop guard)."""
    col_dir = column_dir(page_id, col)
    if not col_dir.is_dir():
        return False
    return any(col_dir.glob("line_*.txt"))


def line_image_path(page_id: str, col: int, line: int) -> Path | None:
    """Path to a line's PNG, whether placed or rejected; None if absent."""
    col_dir = column_dir(page_id, col)
    stem = f"line_{line:03d}.png"
    placed = col_dir / stem
    if placed.exists():
        return placed
    rejected = col_dir / "rejected" / stem
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


def apply_label(page_id: str, col: int, line: int, action: str, text: str = "") -> dict:
    """Mutate the filesystem to reflect a label action; return new status + text.

    action ∈ {"submit", "empty", "reject"}. Every action first un-rejects so
    state transitions out of "rejected" are automatic and self-cleaning.
    """
    col_dir = column_dir(page_id, col)
    stem = f"line_{line:03d}"
    txt = col_dir / f"{stem}.txt"

    if action == "reject":
        rejected_dir = col_dir / "rejected"
        rejected_dir.mkdir(parents=True, exist_ok=True)
        png = col_dir / f"{stem}.png"
        if png.exists():
            shutil.move(str(png), str(rejected_dir / f"{stem}.png"))
        txt.unlink(missing_ok=True)
        return {"status": "rejected", "text": ""}

    _unreject(col_dir, line)

    if action == "submit":
        txt.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
        return {"status": line_status(col_dir, line), "text": line_text(col_dir, line)}

    if action == "empty":
        txt.write_text("", encoding="utf-8")
        return {"status": "empty", "text": ""}

    raise ValueError(f"Unknown action: {action!r}")
