"""Check the paddle-filled baseline against its committed sha256 manifest.

Reviewed pages already refuse edits if their baseline changes (``storage._guard_baseline``).
The manifest covers the rest: an unreviewed page may be regenerated, but a comparison
against earlier output needs to know it was, so the change is reported (and
``tests/test_baseline_manifest.py`` fails) until it is accepted here.

    uv run python -m dev.line_review.baseline_manifest            # report changes
    uv run python -m dev.line_review.baseline_manifest --accept   # record the current hashes
"""

from __future__ import annotations

import argparse

from . import storage


def changes(recorded: dict[int, str], current: dict[int, str]) -> dict[str, list[int]]:
    """Pages whose hash changed, appeared, or disappeared since ``recorded``."""
    return {
        "changed": sorted(p for p in recorded.keys() & current.keys() if recorded[p] != current[p]),
        "added": sorted(current.keys() - recorded.keys()),
        "removed": sorted(recorded.keys() - current.keys()),
    }


def reviewed(pages: list[int]) -> list[int]:
    """The subset of ``pages`` that has a review (whose edits a change would invalidate)."""
    return [p for p in pages if storage.review_path(p).exists()]


def report(diff: dict[str, list[int]]) -> str:
    lines = []
    for kind, pages in diff.items():
        if pages:
            hit = reviewed(pages)
            lines.append(f"{kind}: {pages}" + (f"  (reviewed: {hit})" if hit else ""))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--accept", action="store_true",
                    help="record the current baseline hashes as the manifest")
    args = ap.parse_args()
    current = storage.current_baseline_hashes()
    diff = changes(storage.baseline_manifest(), current)
    text = report(diff)
    print(text or f"baseline matches the manifest ({len(current)} pages)")
    if args.accept and text:
        storage.write_manifest(current)
        print(f"wrote {storage.MANIFEST_PATH}")


if __name__ == "__main__":
    main()
