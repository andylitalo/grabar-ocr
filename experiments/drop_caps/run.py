"""Drop-cap lines: does the tall capital make the OCR engines misread the body text? (2026-11-26)

See README.md next to this file. Each step runs in the environment its engine needs; all
outputs go to ``runs/drop_caps/`` (git-ignored):

    uv run python experiments/drop_caps/run.py crops                          # detect, write crops
    .venv_ml/bin/python experiments/drop_caps/run.py tess                     # Tesseract hye-calfa-n
    dev/lineseg_survey/.venv-hyocr/bin/python experiments/drop_caps/run.py paddle
    uv run python experiments/drop_caps/run.py score

``crops`` finds drop caps from the ink of every verified line (no review op needed) and
writes three crops of each: ``orig`` (``crops.line_crop``, what the engines read today),
``body`` (the capital whitened and the crop cut to the body text) and ``scaled`` (the body
with the capital shrunk to the body's capital height and set in front). ``tess`` and
``paddle`` read all three with the Phase 11 settings. ``score`` prints the tables in the
README. Tesseract and Paddle are deterministic, so a rerun reproduces them.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
OUT = REPO / "runs" / "drop_caps"
VARIANTS = ("orig", "body", "scaled")

# Detection. A drop cap is the tallest blob in the left LEFT of the crop, at least
# CAP_RATIO times the text band (median blob top to median blob bottom, about the
# x-height). A letter with an ascender and a descender is about 2.6 bands; the shortest
# real drop caps found are 3.2.
CAP_RATIO = 3.0
LEFT = 0.25
MIN_AREA = 30  # px; smaller blobs are dust
INK = 140      # grey level below which a pixel is ink
PAD = 6        # px kept around the body text
GAP = 8        # px left where the capital's empty columns are closed up


# --- crops (repo venv) -------------------------------------------------------------


def review_ops() -> dict[int, dict[str, dict]]:
    """page -> baseline line key -> that line's ``initial`` (or legacy ``grow``) op."""
    out: dict[int, dict[str, dict]] = {}
    for f in (REPO / "data/lineseg_survey/paddle-filled/reviews").glob("page_*.review.json"):
        page = int(f.name.split("_")[1].split(".")[0])
        rec = json.loads(f.read_text(encoding="utf-8"))
        for op in rec["ops"] if isinstance(rec, dict) else rec:
            if op.get("op") in ("initial", "grow"):
                out.setdefault(page, {})[op["line"]] = op
    return out


def find_cap(img):
    """The drop cap in a line crop, or None: its pixel mask and box, the body's pixel mask,
    rows and ink columns, and the text band."""
    import cv2
    import numpy as np

    a = np.asarray(img)
    n, lab, st, _ = cv2.connectedComponentsWithStats((a < INK).astype(np.uint8), connectivity=8)
    blobs = {i: tuple(int(v) for v in st[i][:4]) for i in range(1, n) if st[i][4] >= MIN_AREA}
    if len(blobs) < 3:
        return None
    W = a.shape[1]
    mt = statistics.median(y for _, y, _, _ in blobs.values())
    mb = statistics.median(y + h for _, y, _, h in blobs.values())
    band = mb - mt
    left = [i for i, b in blobs.items() if b[0] + b[2] / 2 < LEFT * W]
    if band <= 0 or not left:
        return None
    top = max(left, key=lambda i: blobs[i][3])
    if blobs[top][3] < CAP_RATIO * band:
        return None
    # The capital's other pieces (a Շ's hook and foot, a decorated swash, Ա's second
    # stroke), grown until nothing more joins: the window follows the capital as it grows,
    # but never reaches far into the text (accents above it would chain).
    caps, cw = {top}, blobs[top][2]
    limit = blobs[top][0] + 3.5 * cw
    changed = True
    while changed:
        changed = False
        cx1 = min(blobs[k][0] for k in caps)
        cx2 = max(blobs[k][0] + blobs[k][2] for k in caps)
        for i, (x, y, w, h) in blobs.items():
            if i in caps:
                continue
            off_band = not (mt - 0.3 * band <= y + h / 2 <= mb + 0.3 * band)
            near = cx1 - 0.3 * cw <= x + w / 2 <= min(cx2 + cw, limit)
            stroke = h >= max(0.5 * blobs[top][3], 2.8 * band) and x + w / 2 <= cx2 + 1.2 * cw
            if (off_band and near) or stroke:
                caps.add(i)
                changed = True
    cap_mask = np.isin(lab, list(caps))
    # A capital touching the first letters is one blob with them: it is capital only up to
    # its last column that reaches outside the text band (with room for ascenders and
    # descenders); the rest of that blob is body text.
    outside = cap_mask.copy()
    outside[max(0, int(mt - 0.6 * band)):max(0, int(mb + 0.6 * band))] = False
    reach = outside.any(axis=0)
    end = int(np.nonzero(reach)[0].max()) + 1 if reach.any() else W
    spill = cap_mask.copy()
    spill[:, :end] = False
    cap_mask[:, end:] = False
    body_mask = np.isin(lab, [i for i in blobs if i not in caps]) | spill
    if not body_mask.any() or not cap_mask.any():
        return None
    rows = np.nonzero(body_mask.any(axis=1))[0]
    ys, xs = np.nonzero(cap_mask)
    return {"cap_mask": cap_mask, "body_mask": body_mask, "band": float(band), "baseline": float(mb),
            "cap_box": (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
            "body_rows": (int(rows.min()), int(rows.max()) + 1)}


def body_and_scaled(img, cap: dict):
    """(body, scaled) crops: the capital whitened and its empty columns closed up to GAP px;
    and the same with the capital scaled to the body's capital height (top of the body's
    ink to its baseline) set in the gap."""
    import cv2
    import numpy as np
    from PIL import Image

    a = np.asarray(img).copy()
    halo = cv2.dilate(cap["cap_mask"].astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2)
    a[halo.astype(bool) & ~cap["body_mask"]] = 255  # the capital and its grey edge
    W, H = img.size
    y1, y2 = cap["body_rows"]
    r1, r2 = max(0, y1 - PAD), min(H, y2 + PAD)
    cx1, cy1, cx2, cy2 = cap["cap_box"]
    cols = cap["body_mask"].any(axis=0)
    # close up only empty columns: the run around the capital's left edge with no body ink
    g1, g2 = cx1, cx1
    while g1 > 0 and not cols[g1 - 1]:
        g1 -= 1
    while g2 < W and not cols[g2]:
        g2 += 1
    left, right = a[r1:r2, :g1], a[r1:r2, g2:]
    gap = np.full((r2 - r1, GAP), 255, np.uint8)

    glyph = np.asarray(img)[cy1:cy2, cx1:cx2].copy()
    glyph[~cap["cap_mask"][cy1:cy2, cx1:cx2]] = 255
    th = max(1, round(cap["baseline"] - y1))
    small = Image.fromarray(glyph).resize((max(1, round(glyph.shape[1] * th / glyph.shape[0])), th),
                                          Image.LANCZOS)
    cap_col = np.full((r2 - r1, small.width), 255, np.uint8)
    cap_col[y1 - r1:y1 - r1 + th] = np.asarray(small)[:(r2 - r1) - (y1 - r1)]

    def trim(parts):
        x = np.hstack([p for p in parts if p.shape[1]])
        ink = np.nonzero((x < INK).any(axis=0))[0]
        return Image.fromarray(x[:, max(0, ink.min() - PAD):ink.max() + 1 + PAD] if len(ink) else x)

    return trim([left, gap, right]), trim([left, gap, cap_col, gap, right])


def cmd_crops() -> None:
    from PIL import Image

    from dev.line_review import crops, storage

    ops = review_ops()
    for v in VARIANTS:
        (OUT / v).mkdir(parents=True, exist_ok=True)
    found, missed, scanned = [], [], 0
    for path in sorted((REPO / "data/verified_lines").glob("page_*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if not rec["lines"]:
            continue
        render = Image.open(storage.render_path(rec["page"])).convert("L")
        page_ops = ops.get(rec["page"], {})
        median_h = statistics.median(l["bbox"][3] - l["bbox"][1] for l in rec["lines"])
        for line in rec["lines"]:
            scanned += 1
            op = next((page_ops[k] for k in [line["key"], *(line.get("derived_from") or [])]
                       if k in page_ops), None)
            if op is None and line["bbox"][3] - line["bbox"][1] < 1.5 * median_h:
                continue  # too short to hold a drop cap
            img = crops.line_crop(render, line)
            cap = find_cap(img)
            if cap is None:
                if op is not None:
                    missed.append(line["id"])
                continue
            body, scaled = body_and_scaled(img, cap)
            for v, im in zip(VARIANTS, (img, body, scaled)):
                im.save(OUT / v / f"{line['id']}.png")
            x1, y1, x2, y2 = cap["cap_box"]
            found.append({"id": line["id"], "op": op is not None, "op_auto": bool(op and op.get("auto")),
                          "initial": line.get("initial"), "cap_box": [x1, y1, x2, y2],
                          "cap_bands": round((y2 - y1) / cap["band"], 2),
                          "crop_h": img.height, "body_h": body.height})
    (OUT / "lines.json").write_text(json.dumps({"found": found, "op_not_found": missed},
                                               ensure_ascii=False, indent=1))
    print(f"{scanned} lines; {len(found)} drop caps found ({sum(f['op'] for f in found)} with an "
          f"initial op, {sum(not f['op'] for f in found)} without); initial ops not found: {missed}")


# --- engines (their own venvs) -----------------------------------------------------


def cmd_tess() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image

    sys.path.insert(0, str(REPO / "ml_vision" / "scripts"))
    from predict_lines_tesseract import recognize  # Phase 11's settings via run_tesseract

    jobs = [(v, p) for v in VARIANTS for p in sorted((OUT / v).glob("*.png"))]
    out: dict[str, dict[str, str]] = {v: {} for v in VARIANTS}
    with ThreadPoolExecutor(8) as ex:
        for (v, p), text in zip(jobs, ex.map(
                lambda j: recognize(Image.open(j[1]), 13, "hye-calfa-n", whitelist=True), jobs)):
            out[v][p.stem] = text
    (OUT / "tess-calfa-n.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("tess-calfa-n:", {v: len(x) for v, x in out.items()})


def cmd_paddle() -> None:
    from armenian_ocr import models
    from armenian_ocr.recognition.paddle import _rec_model_name_from_dir
    from paddleocr import TextRecognition

    rec_dir = models.get_paddle_rec_dir()  # as dev/ocr_eval/run_paddle.py
    model = TextRecognition(model_dir=str(rec_dir), model_name=_rec_model_name_from_dir(str(rec_dir)))
    out: dict[str, dict[str, str]] = {v: {} for v in VARIANTS}
    for v in VARIANTS:
        for p in sorted((OUT / v).glob("*.png")):
            (res,) = model.predict(str(p))
            out[v][p.stem] = res["rec_text"].strip()
    (OUT / "paddle-calfa-tiny.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("paddle-calfa-tiny:", {v: len(x) for v, x in out.items()})


# --- score (repo venv) -------------------------------------------------------------


def cmd_score() -> None:
    from dev.ocr_eval import ceiling, common
    from dev.ocr_eval.score import edits, normalize

    common.use_set("ceiling")
    found = {f["id"]: f for f in json.loads((OUT / "lines.json").read_text())["found"]}
    t = json.loads((OUT / "tess-calfa-n.json").read_text())
    p = json.loads((OUT / "paddle-calfa-tiny.json").read_text())
    n = lambda s: normalize(s, spaces=False)  # noqa: E731  (the scorer's normalization)

    def disagree(keys, v):
        chars = sum(edits(n(t[v][k]), n(p[v][k])) for k in keys)
        total = sum(max(len(n(t[v][k])), 1) for k in keys)
        lines = sum(n(t[v][k]) != n(p[v][k]) for k in keys)
        return f"{100 * lines / len(keys):5.1f}% | {100 * chars / total:5.1f}%"

    others = [k for k in common.load_predictions("tess-calfa-n")["lines"] if k not in found]
    T, P = (common.load_predictions(e)["lines"] for e in ("tess-calfa-n", "paddle-calfa-tiny"))
    o_chars = sum(edits(n(T[k]), n(P[k])) for k in others) / sum(max(len(n(T[k])), 1) for k in others)
    print(f"other lines (n={len(others)}): {100 * sum(n(T[k]) != n(P[k]) for k in others) / len(others):.1f}% "
          f"of lines, {100 * o_chars:.1f}% of characters")
    groups = {"all": list(found), "with an initial op": [k for k in found if found[k]["op"]],
              "without": [k for k in found if not found[k]["op"]]}
    for g, keys in groups.items():
        print(f"\n{g} (n={len(keys)}) | lines | characters")
        for v in VARIANTS:
            print(f"  {v:6s} | {disagree(keys, v)}")

    v4 = common.load_predictions("corr-gemini-3.1-pro-v4+rules")["lines"]
    keys = [k for k in found if k in v4]
    print(f"\nCER against v4's corrected text ({len(keys)} lines; body without its first letter)")
    for v in VARIANTS:
        ref = (lambda k: n(v4[k])[1:]) if v == "body" else (lambda k: n(v4[k]))
        row = [100 * sum(edits(ref(k), n(R[v][k])) for k in keys) / sum(len(ref(k)) for k in keys)
               for R in (t, p)]
        print(f"  {v:6s} | Tesseract {row[0]:4.1f}% | Paddle {row[1]:4.1f}%")

    typed = [k for k in found if found[k]["initial"]]
    print(f"\nfirst letter = the typed initial ({len(typed)} lines)")
    for v in ("orig", "scaled"):
        print(f"  {v:6s} | Tesseract {sum(n(t[v][k])[:1] == found[k]['initial'] for k in typed)} "
              f"| Paddle {sum(n(p[v][k])[:1] == found[k]['initial'] for k in typed)}")

    print("\ntyped ceiling lines (edits from the typed line)")
    for k in found:
        if (ref := ceiling.reference(k)) is not None:
            print(f"  {k}: " + " | ".join(f"{v} T{edits(n(ref), n(t[v][k]))} P{edits(n(ref), n(p[v][k]))}"
                                          for v in VARIANTS))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["crops", "tess", "paddle", "score"])
    {"crops": cmd_crops, "tess": cmd_tess, "paddle": cmd_paddle, "score": cmd_score}[ap.parse_args().step]()


if __name__ == "__main__":
    main()
