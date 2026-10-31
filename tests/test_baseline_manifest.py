"""
The paddle-filled baseline matches its committed sha256 manifest
(data/lineseg_survey/paddle-filled/baseline_sha256.json).

Unreviewed pages may be regenerated, but anything compared against earlier output needs
to know, so a change fails here until it is accepted with
``uv run python -m dev.line_review.baseline_manifest --accept``. A reviewed page's
baseline must not change at all (its ops would no longer apply).
"""

from __future__ import annotations

from dev.line_review import baseline_manifest as bm
from dev.line_review import storage


def test_baseline_matches_the_manifest():
    recorded = storage.baseline_manifest()
    assert recorded, f"no manifest at {storage.MANIFEST_PATH}"
    diff = bm.changes(recorded, storage.current_baseline_hashes())
    assert not any(diff.values()), (
        "paddle-filled differs from its manifest:\n" + bm.report(diff)
        + "\nIf the regeneration was deliberate (and no reviewed page changed), accept it with"
        " `uv run python -m dev.line_review.baseline_manifest --accept`.")
