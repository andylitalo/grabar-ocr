"""
Freeze the Phase 4 scaling experiment — snapshot the exact bytes the
50/150/500-line CER curve was measured on, so a later rebuild can't silently
invalidate the recorded `page_XXXX/line_NNN` ids.

What it captures (all under data/, which is gitignored — a zip here IS the freeze):
  - data/phase4_dataset/    the merged+renumbered lines the ids point into
  - data/frozen_test_set/   the 100-line eval set + manifest.json (id provenance)
  - data/phase4_scaling/    splits_{50,150,500}.json (the nested train ids)

Output: data/backups/phase4_frozen_<UTCstamp>.zip with a SHA256SUMS member
listing every archived file's hash. Also drops a freeze marker
data/phase4_scaling/.frozen so build_phase4_dataset.py knows to refuse a
destructive rebuild (see its --rebuild guard).

Run:
    uv run python data_prep/freeze_phase4.py
"""

from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TARGETS = [
    REPO / "data/phase4_dataset",
    REPO / "data/frozen_test_set",
    REPO / "data/phase4_scaling",
]
BACKUP_DIR = REPO / "data/backups"
FREEZE_MARKER = REPO / "data/phase4_scaling/.frozen"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for t in targets:
        if not t.exists():
            print(f"  WARN: missing, skipping: {t.relative_to(REPO)}")
            continue
        files.extend(sorted(p for p in t.rglob("*") if p.is_file()))
    return files


def main() -> None:
    files = _collect_files(TARGETS)
    if not files:
        raise SystemExit("Nothing to freeze — none of the target dirs exist.")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zip_path = BACKUP_DIR / f"phase4_frozen_{stamp}.zip"

    sums_lines: list[str] = []
    total_bytes = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            arcname = f.relative_to(REPO).as_posix()
            zf.write(f, arcname)
            sums_lines.append(f"{_sha256(f)}  {arcname}")
            total_bytes += f.stat().st_size
        zf.writestr("SHA256SUMS", "\n".join(sums_lines) + "\n")

    # Marker so build_phase4_dataset.py refuses a destructive rebuild without --rebuild.
    FREEZE_MARKER.write_text(
        f"frozen {stamp}\narchive {zip_path.relative_to(REPO)}\n", encoding="utf-8"
    )

    print(f"Froze {len(files)} files ({total_bytes / 1e6:.1f} MB) into:")
    print(f"  {zip_path.relative_to(REPO)}  (+ SHA256SUMS inside)")
    for t in TARGETS:
        if t.exists():
            n = sum(1 for p in t.rglob('*') if p.is_file())
            print(f"    captured {t.relative_to(REPO)}/  ({n} files)")
    print(f"  wrote marker {FREEZE_MARKER.relative_to(REPO)}")


if __name__ == "__main__":
    main()
