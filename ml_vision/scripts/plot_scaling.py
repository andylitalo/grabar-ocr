"""
Plot Phase 4 CER vs. training-set size.

Reads the three finetune_phase4_scale_*/results.json files, writes
reports/phase4_scaling.csv and reports/phase4_scaling.png (CER vs. n_train,
points + line, each point annotated). matplotlib only — no W&B.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: write a file, no display needed
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parent.parent.parent
CHECKPOINTS = REPO / "ml_vision/checkpoints"
REPORTS = REPO / "reports"


def load_results() -> list[dict]:
    rows: list[dict] = []
    for results_path in CHECKPOINTS.glob("finetune_phase4_scale_*/results.json"):
        rows.append(json.loads(results_path.read_text(encoding="utf-8")))
    if not rows:
        raise SystemExit(
            f"No results.json found under {CHECKPOINTS}/finetune_phase4_scale_*/. "
            "Run finetune_phase4.py for each splits file first."
        )
    rows.sort(key=lambda r: r["n_train"])
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n_train", "eval_cer"])
        for r in rows:
            writer.writerow([r["n_train"], r["eval_cer"]])


def write_plot(rows: list[dict], path: Path) -> None:
    xs = [r["n_train"] for r in rows]
    ys = [r["eval_cer"] for r in rows]

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(xs, ys, marker="o", color="#1f77b4")
    for x, y in zip(xs, ys):
        ax.annotate(f"{y:.3f}", (x, y), textcoords="offset points", xytext=(0, 8), ha="center")

    ax.set_xlabel("Training set size (lines)")
    ax.set_ylabel("Held-out CER (fraction, 100 frozen lines)")
    ax.set_title("Phase 4 — CER vs. training-set size")
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    rows = load_results()

    csv_path = REPORTS / "phase4_scaling.csv"
    png_path = REPORTS / "phase4_scaling.png"
    write_csv(rows, csv_path)
    write_plot(rows, png_path)

    print("Scaling results:")
    for r in rows:
        print(f"  n_train={r['n_train']:>4}  CER={r['eval_cer']:.4f} ({r['eval_cer'] * 100:.1f}%)")
    print(f"Wrote {csv_path.relative_to(REPO)}")
    print(f"Wrote {png_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
