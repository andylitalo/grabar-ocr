"""
pipeline.py
Orchestration over the existing data_prep functions.

Turns a selected page PDF into a cached, full-page-deskewed render, then into
per-column PNGs (data/columns/) and per-line PNGs (data/lines/). Reuses, and does
not reimplement:
  - data_prep.pdf_slicer.pdf_to_images  (PDF -> page PNG @ DPI)
  - data_prep.deskew.deskew_page         (projection-profile full-page deskew)
  - data_prep.line_cropper.crop_lines    (column PNG -> line PNGs)

The render the UI draws boxes on is the deskewed page, so the boxes a user sees
are exactly the geometry that gets cropped (no hidden per-column rotation).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import cv2

from . import storage

# Make the sibling `data_prep/` package importable.
sys.path.insert(0, str(storage.REPO))
from data_prep.deskew import deskew_page  # noqa: E402
from data_prep.line_cropper import crop_lines  # noqa: E402
from data_prep.line_filter import (  # noqa: E402
    DEFAULT_INK_FACTOR,
    classify_page,
    line_features,
    page_median_ink,
)
from data_prep.pdf_slicer import pdf_to_images  # noqa: E402

RENDER_DPI = 300

# Cache filename for the deskewed render. Versioned apart from any legacy
# `page.png` so stale, pre-deskew caches are never silently reused.
_RENDER_NAME = "page_deskew.png"
# Residual per-column deskew is bounded: the page is already deskewed, so this
# only mops up tiny leftover skew and must never apply a large rotation.
_RESIDUAL_MAX_ANGLE = 0.5


def render_page(n: int, dpi: int = RENDER_DPI) -> Path:
    """Render page-1 of data/pages/{n}.pdf, deskew it, and cache the result.

    Returns the path to the cached deskewed grayscale PNG. The applied skew
    correction is recorded in a sidecar `page_deskew.json`. Re-renders if missing.
    """
    pdf_path = storage.page_pdf_path(n)
    if not pdf_path.exists():
        raise FileNotFoundError(f"No page PDF at {pdf_path}")

    page_id = storage.page_id_for(n)
    out_png = storage.WORK_DIR / page_id / _RENDER_NAME
    if out_png.exists():
        return out_png

    out_png.parent.mkdir(parents=True, exist_ok=True)
    # pdf_to_images names outputs page_0001.png (1-based within the file); a
    # one-page PDF yields exactly one image. Render to a temp slot, deskew, cache.
    rendered = pdf_to_images(pdf_path, out_png.parent, dpi=dpi)
    if not rendered:
        raise RuntimeError(f"No pages rendered from {pdf_path}")
    raw_path = Path(rendered[0])
    gray = cv2.imread(str(raw_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise RuntimeError(f"Cannot read rendered page: {raw_path}")
    raw_path.unlink(missing_ok=True)

    deskewed, angle = deskew_page(gray)
    cv2.imwrite(str(out_png), deskewed)
    sidecar = out_png.with_suffix(".json")
    sidecar.write_text(json.dumps({"deskew_angle": angle, "dpi": dpi}), encoding="utf-8")
    return out_png


def _rotate(img, angle_deg: float):
    """Rotate ``img`` about its centre by ``angle_deg`` (same size, white border)."""
    if abs(angle_deg) < 1e-3:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle_deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=255)


def preview_render(n: int, manual_angle: float = 0.0) -> Path:
    """Path to the cached deskewed render, further un-skewed by ``manual_angle``.

    ``manual_angle`` is the human reference-line residual (deg): the page is
    rotated by ``-manual_angle`` so the user sees (and draws boxes on) the same
    frame that ``crop_columns_and_lines`` will crop from. angle 0 returns the
    cached render unchanged; otherwise a per-angle preview PNG is cached alongside.
    """
    base = render_page(n)
    if abs(manual_angle) < 1e-3:
        return base
    out = base.parent / f"page_deskew_m{manual_angle:+06.2f}.png"
    if out.exists():
        return out
    img = cv2.imread(str(base), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Cannot read render: {base}")
    cv2.imwrite(str(out), _rotate(img, -manual_angle))
    return out


def deskew_angle(n: int) -> float:
    """Skew correction (degrees) applied to page n's cached render, 0 if unknown."""
    sidecar = storage.WORK_DIR / storage.page_id_for(n) / _RENDER_NAME
    sidecar = sidecar.with_suffix(".json")
    if not sidecar.exists():
        return 0.0
    return float(json.loads(sidecar.read_text(encoding="utf-8")).get("deskew_angle", 0.0))


def page_dimensions(render_path: Path) -> tuple[int, int]:
    """(width, height) in full-resolution pixels of a rendered page."""
    image = cv2.imread(str(render_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Cannot read render: {render_path}")
    h, w = image.shape[:2]
    return w, h


def default_columns(width: int, height: int) -> list[dict]:
    """Two suggested column boxes the user then nudges (left/right halves)."""
    mx = round(0.02 * width)
    my = round(0.01 * height)
    gutter = round(0.02 * width)
    mid = width // 2
    return [
        {"x1": mx, "y1": my, "x2": mid - gutter // 2, "y2": height - my},
        {"x1": mid + gutter // 2, "y1": my, "x2": width - mx, "y2": height - my},
    ]


def suggested_columns(n: int) -> list[dict]:
    """Auto-detected column boxes for page n, or the hardcoded halves fallback.

    Runs the vertical-projection detector on the deskewed render. If it is not
    confident (edge-case layout: header, full-page image, unclear gutter), returns
    ``default_columns`` so the UI still shows sensible starting boxes to nudge.
    """
    from data_prep.column_detector import detect_columns  # noqa: E402

    render_path = render_page(n)
    page = cv2.imread(str(render_path), cv2.IMREAD_GRAYSCALE)
    if page is None:
        raise FileNotFoundError(f"Cannot read render: {render_path}")
    boxes, diag = detect_columns(page)
    if diag.get("confident") and boxes:
        return boxes
    h, w = page.shape[:2]
    return default_columns(w, h)


def suggested_regions(n: int) -> list[dict]:
    """Auto-detected typed regions to seed the annotator: ``[{type, box}]``.

    Runs ``detect_regions`` on the deskewed render. When confident, returns its
    ordered, typed regions; otherwise falls back to the two ``default_columns``
    halves as ``left``/``right`` so the UI always has sensible starting boxes. Each
    box seeds both the region's min and max in the annotator (the human then nudges).
    """
    from data_prep.column_detector import detect_regions  # noqa: E402

    render_path = render_page(n)
    page = cv2.imread(str(render_path), cv2.IMREAD_GRAYSCALE)
    if page is None:
        raise FileNotFoundError(f"Cannot read render: {render_path}")
    regions, diag = detect_regions(page)
    if diag.get("confident") and regions:
        return [
            {"type": r["type"], "box": {k: int(r[k]) for k in ("x1", "y1", "x2", "y2")}}
            for r in regions
        ]
    h, w = page.shape[:2]
    cols = default_columns(w, h)
    return [{"type": "left", "box": cols[0]}, {"type": "right", "box": cols[1]}]


def detector_meta() -> dict:
    """Snapshot of the detector rule, recorded in every truth file for reproducibility."""
    return {
        "ink_factor": DEFAULT_INK_FACTOR,
        "rule": f"glyph_count==0 OR ink>{DEFAULT_INK_FACTOR}x page-median",
    }


def line_nonchar_verdicts(page_id: str) -> dict[str, dict]:
    """Per-line detector verdict for a page's placed line crops.

    Returns ``{"column_Y/line_NNN": {non_character, glyph_count, ink_ratio}}``,
    computed with the SAME data_prep.line_filter functions the production detector
    (predict_lines.detect_nonchar) uses, so the UI and the detector can never
    disagree. When an offline ``predictions.json`` already carries a
    ``non_character`` field for the page, those values are reused verbatim for exact
    parity with that run; otherwise features are computed live (~ms/line, no OCR).
    """
    page_dir = storage.DATA_LINES / page_id
    if not page_dir.is_dir():
        return {}

    # Exact parity path: reuse a prior predict_lines run if it recorded non_character.
    pred = _predictions_nonchar(page_id)
    if pred:
        return pred

    feats: dict[str, dict] = {}
    for region_dir in storage.list_region_dirs(page_id):
        region = region_dir.name
        for png in sorted(region_dir.glob("line_*.png")):
            gray = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                continue
            feats[f"{region}/{png.stem}"] = line_features(gray)

    median = page_median_ink(feats)
    flags = classify_page(feats)
    return {
        line_id: {
            "non_character": flags[line_id],
            "glyph_count": f["glyph_count"],
            "ink_ratio": (f["ink_density"] / median) if median else 0.0,
        }
        for line_id, f in feats.items()
    }


def _predictions_nonchar(page_id: str) -> dict[str, dict]:
    """Reuse a predictions.json ``non_character`` snapshot if one exists, else {}.

    Only returns data when at least one line carries a non_character field (a run
    from a detector-aware predict_lines pass); a plain prediction set yields {} so
    the caller recomputes live.
    """
    pred_root = storage.DATA_PREDICTIONS
    if not pred_root.is_dir():
        return {}
    for tag_dir in sorted(pred_root.iterdir()):
        pred_json = tag_dir / page_id / "predictions.json"
        if not pred_json.exists():
            continue
        data = json.loads(pred_json.read_text(encoding="utf-8"))
        lines = data.get("lines", {})
        if any("non_character" in v for v in lines.values()):
            return {
                lid: {
                    "non_character": bool(v.get("non_character", False)),
                    "glyph_count": v.get("glyph_count"),
                    "ink_ratio": v.get("ink_ratio"),
                }
                for lid, v in lines.items()
            }
    return {}


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def _default_region_types(count: int) -> list[str]:
    """Region types for the legacy box flow when none are given explicitly.

    Two boxes are a left/right column pair; one box is a single-column band.
    The region annotator (Phase 6 UI) supplies explicit types for other shapes.
    """
    if count == 2:
        return ["left", "right"]
    if count == 1:
        return ["single"]
    return ["single"] * count


def crop_columns_and_lines(
    n: int,
    columns: list[dict],
    do_deskew: bool = True,
    padding: int = 4,
    method: str = storage.METHOD_HUMAN,
    region_types: list[str] | None = None,
    manual_angle: float = 0.0,
) -> list[dict]:
    """Crop each region from the page render and segment it into line PNGs.

    Each rectangle is in full-resolution page pixels, in reading order. Region i
    (1-based) of type ``region_types[i-1]`` is written to
    data/columns/{artifact_id}_region_NN_<type>.png, then crop_lines() fills
    data/lines/{artifact_id}/region_NN_<type>/, where artifact_id = page_XXXX_{method}
    ("human" via the UI, "auto" via auto_slice). ``region_types`` defaults to
    left/right for two boxes (a plain two-column page) or single for one.
    ``manual_angle`` un-skews the render by the human reference-line residual before
    cropping, so boxes drawn on the previewed (rotated) frame line up exactly.
    Returns per-region line counts. The render is method-independent (one cache).
    """
    page_id = storage.page_artifact_id(n, method)
    types = region_types if region_types is not None else _default_region_types(len(columns))
    if len(types) != len(columns):
        raise ValueError(f"region_types ({len(types)}) must match columns ({len(columns)})")
    render_path = render_page(n)
    page = cv2.imread(str(render_path), cv2.IMREAD_GRAYSCALE)
    if page is None:
        raise FileNotFoundError(f"Cannot read render: {render_path}")
    page = _rotate(page, -manual_angle)  # match the previewed frame boxes were drawn on
    h, w = page.shape[:2]

    storage.DATA_COLUMNS.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for i, (box, rtype) in enumerate(zip(columns, types), start=1):
        x1 = _clamp(int(box["x1"]), 0, w)
        y1 = _clamp(int(box["y1"]), 0, h)
        x2 = _clamp(int(box["x2"]), 0, w)
        y2 = _clamp(int(box["y2"]), 0, h)
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))

        crop = page[y1:y2, x1:x2]
        if do_deskew:
            # The page render is already deskewed; this only corrects tiny
            # residual per-column skew (bounded), never a large rotation.
            crop, _ = deskew_page(crop, max_abs_angle=_RESIDUAL_MAX_ANGLE)

        region = storage.region_dirname(i, rtype)
        column_png = storage.DATA_COLUMNS / f"{page_id}_{region}.png"
        cv2.imwrite(str(column_png), crop)

        region_dir = storage.region_dir(page_id, region)
        # Re-crop: clear stale line PNGs (and rejected/) before re-segmenting.
        if region_dir.exists():
            shutil.rmtree(region_dir)
        saved = crop_lines(column_png, region_dir, padding=padding)
        results.append(
            {"region": region, "region_type": rtype, "column": i, "line_count": len(saved)}
        )

    return results
