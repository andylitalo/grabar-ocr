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


def test_a_worse_retry_does_not_replace_the_first_answer():
    """p508 (2026-11-23): 1 fallback, then a retry that skipped a row and shifted the rest."""
    from dev.ocr_eval.correct import ENGINES, correct_page
    keys = ["k1", "k2", "k3"]
    texts = {"k1": "Բշ. Ճաշու սաղ.", "k2": "Եւ առաւօտու օրհնութիւն", "k3": "Տէր թագաւորեաց"}
    preds = {e: dict(texts) for e in ENGINES}
    answers = iter([f"1\t{texts['k1']}\n2\t{texts['k2']}",    # line 3 missing
                    f"1\t{texts['k2']}\n2\t{texts['k3']}"])   # shifted: lines 1-3 fall back
    usage = [{"in": 10, "out": 1, "served_by": "m"}, {"in": 20, "out": 2, "served_by": "m"}]
    calls = iter(zip(answers, usage))
    corrected, reasons, u = correct_page(lambda: next(calls), keys, preds)
    assert reasons == {"k3": "missing"} and corrected == texts
    assert (u["in"], u["out"]) == (30, 3)  # both attempts are billed


# --- re-asking the lines that fall back (2026-11-25) -----------------------------------

WORDS = ["Բշ. Ճաշու սաղ.", "Եւ առաւօտու օրհնութիւն", "Տէր թագաւորեաց", "Շարական գկ.",
         "Առակ. Թ. Իմաստութիւն", "Սաղմոս Դաւթի", "Աւետարան ըստ Մատթէոսի", "Յերրորդում աւուր",
         "Կոզմայի եւ Դամիանոսի", "Երկրորդ կիւրակէ"]


def _page(n=10):
    from dev.ocr_eval.correct import ENGINES
    keys = [f"k{i}" for i in range(1, n + 1)]
    texts = dict(zip(keys, WORDS[:n]))
    return keys, texts, {e: dict(texts) for e in ENGINES}


def test_reask_windows_take_neighbours_merge_and_stay_on_the_page():
    from dev.ocr_eval.correct import reask_windows
    keys = [f"k{i}" for i in range(1, 21)]
    assert reask_windows(keys, ["k10"], 3) == [(6, 13)]             # 3 either side
    assert reask_windows(keys, ["k1"], 3) == [(0, 4)]               # clipped at the top
    assert reask_windows(keys, ["k20"], 3) == [(16, 20)]            # and at the bottom
    assert reask_windows(keys, ["k5", "k9"], 3) == [(1, 12)]        # overlapping: one request
    assert reask_windows(keys, ["k3", "k17"], 3) == [(0, 6), (13, 20)]


def test_reask_takes_only_the_fallback_line_from_its_window():
    from dev.ocr_eval.correct import reask
    keys, texts, preds = _page()
    corrected = dict(texts, k5="OCR reading kept")      # k5 fell back on the page
    asked = []

    def ask(window):
        asked.append(window)
        # the window's answer also "changes" a neighbour: that must be ignored
        rows = [texts[k] + (" ՚ի" if k == "k4" else "") for k in window]
        return "\n".join(f"{n}\t{t}" for n, t in enumerate(rows, 1)), {"in": 5, "out": 1}

    out, still, u = reask(ask, keys, preds, corrected, ["k5"], context=3)
    assert asked == [["k2", "k3", "k4", "k5", "k6", "k7", "k8"]]
    assert out["k5"] == texts["k5"] and out["k4"] == texts["k4"]   # neighbour keeps the page's
    assert still == {} and (u["in"], u["out"]) == (5, 1)


def test_a_line_that_falls_back_again_keeps_the_ocr():
    from dev.ocr_eval.correct import ENGINES, reask
    keys, texts, preds = _page()
    # The window's answer shifts by a row again: k5's slot holds k6's text.
    answer = "\n".join(f"{n}\t{texts[k]}" for n, k in enumerate(["k2", "k3", "k4", "k6", "k7", "k8"], 1))
    out, still, _ = reask(lambda w: (answer, {"in": 1, "out": 1}), keys, preds,
                          dict(texts), ["k5"], context=3)
    assert still == {"k5": "shifted"} and out["k5"] == preds[ENGINES[1]]["k5"]


# --- why a line fell back: misaligned (ask again) or too far (a person reviews) -----------

# p508.011 (2026-11-25): a heading both engines garbled, and Gemini's reconstruction.
HEADING = {"tess-calfa-n": "Շաք.-է տատհուի 1ա-", "paddle-calfa-tiny": "աթ, տն էսրոյն րիդորիԼու"}
HEADING_ANSWER = "Շաբաթ, տօն է սրբոյն Գրիգորի Լու-"


def test_each_kind_of_fallback_gets_its_reason():
    from dev.ocr_eval.correct import ENGINES, parse_reasons
    keys, texts, preds = _page(6)
    for e in ENGINES:
        preds[e]["k6"] = HEADING[e]
    rows = {1: texts["k1"],                                    # right
            2: "A: " + texts["k2"] + " ‖ B: " + texts["k2"],   # echoed
            # 3: missing
            4: texts["k5"],                                    # k5's text in k4's slot: shifted
            5: texts["k5"],                                    # right
            6: HEADING_ANSWER}                                 # too far, and no neighbour's
    answer = "\n".join(f"{n}\t{t}" for n, t in rows.items())
    out, reasons = parse_reasons(answer, keys, preds)
    assert reasons == {"k2": "echoed", "k3": "missing", "k4": "shifted", "k6": "too_far"}
    assert out["k1"] == texts["k1"] and out["k6"] == preds[ENGINES[1]]["k6"]


def test_a_too_far_line_alone_is_not_asked_again():
    from dev.ocr_eval.correct import ENGINES, correct_page
    keys, texts, preds = _page(3)
    for e in ENGINES:
        preds[e]["k3"] = HEADING[e]
    calls = []

    def call():
        calls.append(1)
        return f"1\t{texts['k1']}\n2\t{texts['k2']}\n3\t{HEADING_ANSWER}", {"in": 1, "out": 1}

    _, reasons, _ = correct_page(call, keys, preds)
    assert reasons == {"k3": "too_far"} and len(calls) == 1


def test_a_shifted_answer_is_asked_again():
    from dev.ocr_eval.correct import correct_page
    keys, texts, preds = _page(4)
    answers = iter([  # a row dropped and the rest renumbered, then a good answer
        "\n".join(f"{n}\t{texts[k]}" for n, k in enumerate(["k1", "k3", "k4"], 1)),
        "\n".join(f"{n}\t{texts[k]}" for n, k in enumerate(keys, 1))])
    corrected, reasons, _ = correct_page(lambda: (next(answers), {"in": 1, "out": 1}), keys, preds)
    assert reasons == {} and corrected == texts

