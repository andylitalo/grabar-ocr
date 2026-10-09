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


def test_apostrophe_forms_are_folded_but_a_missing_one_still_counts():
    assert score.normalize("'ի") == score.normalize("՚ի") == score.normalize("’ի")
    assert score.edits(score.normalize("՚ի տեղւոյս"), score.normalize("ի տեղւոյս")) == 1


def test_apostrophe_rule_marks_only_standalone_i():
    from dev.ocr_eval.rules import apply_rules
    assert apply_rules("ի վերդ ես։") == "՚ի վերդ ես։"
    assert apply_rules("Կուսին ի յԱննայէ։") == "Կուսին ՚ի յԱննայէ։"
    assert apply_rules("Կուսին ՚ի յԱննայէ") == "Կուսին ՚ի յԱննայէ"   # already there
    assert apply_rules("ինքն իմ ի") == "ինքն իմ ՚ի"                       # only the word ի


def test_correction_parse_strips_a_kept_label_and_rejects_shifted_lines():
    from dev.ocr_eval.correct import ENGINES, parse
    keys = ["k1", "k2", "k3"]
    preds = {ENGINES[0]: {"k1": "Բչ. Ճաշու սաղ.", "k2": "Եւ առաւօտու օրհնութիւն", "k3": "Տէր թագաւորեաց"},
             ENGINES[1]: {"k1": "Բշ. Ճաշու սաղ.", "k2": "Եւ առաւօտու օրհնութիւն", "k3": "Տէր թագաւորեաց"}}
    # Line 1 chose reading B but kept its label; line 2 carries line 3's text (a row was
    # skipped); line 3 is missing.
    out, fallbacks = parse("1\tB: Բշ. Ճաշու սաղ.\n2\tՏէր թագաւորեաց", keys, preds)
    assert out["k1"] == "Բշ. Ճաշու սաղ."
    assert out["k2"] == "Եւ առաւօտու օրհնութիւն" and out["k3"] == "Տէր թագաւորեաց"
    assert fallbacks == 2
