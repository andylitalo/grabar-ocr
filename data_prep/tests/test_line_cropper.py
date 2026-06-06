"""Unit tests for the line-slicing over-segmentation guard.

These build synthetic horizontal-projection profiles (humps = text lines,
troughs = inter-line gaps) and assert that `find_line_boundaries`:
  - splits a run that fuses 2 or 3 lines (the merged-crop bug), and
  - never over-splits a single tall line that has no deep interior trough.

A page always carries several normal single lines so the per-page *median* line
height is well defined — that median is what the guard compares against.
"""

from __future__ import annotations

import numpy as np

from data_prep.line_cropper import find_line_boundaries

PEAK = 1000.0
WIDTH = 7.0  # gaussian sigma giving a ~39-row single-line run above the 2% gate


def _hump(length: int, center: float, width: float = WIDTH, peak: float = PEAK) -> np.ndarray:
    x = np.arange(length, dtype=np.float32)
    return peak * np.exp(-0.5 * ((x - center) / width) ** 2)


def _profile(length: int, centers: list[float], width: float = WIDTH) -> np.ndarray:
    prof = np.zeros(length, dtype=np.float32)
    for c in centers:
        prof += _hump(length, c, width=width)
    return prof


def test_two_line_merge_is_split() -> None:
    # 3 well-separated single lines set the median; one merged pair (35 px apart,
    # trough ~9% of peak so it stays above the 2% gate and reads as one run).
    prof = _profile(400, [40, 110, 180, 280, 315])
    bounds = find_line_boundaries(prof)
    assert len(bounds) == 5, bounds  # 3 singles + 2 from the split merged pair

    # The cut between the merged pair sits in the true trough (~297).
    tops = sorted(t for t, _ in bounds)
    cut = next(t for t in tops if 280 <= t <= 320)
    assert 287 <= cut <= 307, cut


def test_three_line_merge_is_split() -> None:
    # 3 singles + a fused triple (260/295/330) -> one run ~2.8x median -> 3 pieces.
    prof = _profile(400, [40, 110, 180, 260, 295, 330])
    bounds = find_line_boundaries(prof)
    assert len(bounds) == 6, bounds


def test_single_tall_line_is_not_oversplit() -> None:
    # 3 normal lines + one genuinely single but wide line (~1.7x median height,
    # no interior trough). The depth check must keep it whole.
    prof = _profile(400, [40, 110, 180], width=WIDTH)
    prof += _hump(400, 300, width=12.0)  # taller single run, smooth single peak
    bounds = find_line_boundaries(prof)
    assert len(bounds) == 4, bounds


def test_clean_single_lines_unchanged() -> None:
    # Sanity: well-separated single lines map 1:1 to boundaries.
    prof = _profile(400, [40, 110, 180, 250, 320])
    bounds = find_line_boundaries(prof)
    assert len(bounds) == 5, bounds


def test_empty_profile() -> None:
    assert find_line_boundaries(np.zeros(100, dtype=np.float32)) == []
