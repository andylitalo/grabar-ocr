"""Tests for the Phase 11 scorer's normalization and CER (dev.ocr_eval.score)."""

from __future__ import annotations

from dev.ocr_eval import score


def test_look_alike_punctuation_is_folded():
    assert score.normalize("գը֊") == score.normalize("գը-")
    assert score.normalize("Եբր․") == score.normalize("Եբր.")
    assert score.normalize("ասա։") == score.normalize("ասա:")
    assert score.normalize("գը֊", fold=False) != score.normalize("գը-", fold=False)


def test_spacing_around_punctuation_can_be_ignored():
    ref, hyp = "Բ. 11. Քանզի", "Բ . 11 . Քանզի"
    assert score.edits(score.normalize(ref), score.normalize(hyp)) == 2
    assert score.edits(score.normalize(ref, spaces=False), score.normalize(hyp, spaces=False)) == 0


def test_pooled_cer_weights_by_reference_length():
    assert score.pooled([(1, 10), (0, 30)]) == 1 / 40
    assert score.edits("աբգ", "") == 3 and score.edits("", "աբ") == 2
