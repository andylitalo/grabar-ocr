"""
Grabar → English translation — the pipeline's final (5th) stage.

This is the *translation* counterpart to ``digitize_page`` / ``llm_correct``: those
turn line crops into corrected Grabar text; this turns a corrected Grabar **page**
into faithful English. It reuses llm_correct's tested provider primitives unchanged
(``MODELS``, ``CALL_FN``, ``PRICE_PER_MTOK``, ``MAX_TOKENS``, the retry/backoff and
per-provider clients) so translation behaviour, cost accounting, and credit-failure
handling are identical to the correction path; only the prompt and the (non-scored)
output differ.

Translation is **page-by-page**: the whole corrected page is sent as one request so
the model has full liturgical context (a citation that opens on one line and closes
on the next, a tone marker that governs the hymn below it). No scoring — there is no
English ground truth; quality is judged by Claude against the corrected Grabar.

Runs in the BASE venv (SDKs only, no torch), exactly like correct_llm.
"""

from __future__ import annotations

import llm_correct as lc  # tested primitives: MODELS, CALL_FN, PRICE_PER_MTOK, MAX_TOKENS, clients

# ── Translation prompt ───────────────────────────────────────────────────────────
# Domain prompt for Grabar liturgical / lectionary text. Mirrors the validated
# Gemini-console style saved under translations/gemini/page_48{6,7}.txt: liturgical
# abbreviations expanded, scripture citations rendered in standard English form,
# line/item structure preserved, [brackets] for clarifications and transliterated
# tone/hymn names. User-refinable — re-run with force=True after editing.
TRANSLATE_SYSTEM = (
    "You translate Classical Armenian (Grabar) LITURGICAL / LECTIONARY text into "
    "clear, faithful English. The text is a church service directory (a Tonatsuyts / "
    "lectionary): rubrics, scripture citations, psalm and hymn references, and tone "
    "markers, mostly in terse abbreviated form.\n\n"
    "GOAL: preserve the MEANING and INFORMATION of every line. Formatting need not "
    "match, but no item may be dropped or invented.\n\n"
    "RULES:\n"
    "- Translate faithfully; do not add commentary, theology, or content not present.\n"
    "- EXPAND liturgical abbreviations to their full English sense, e.g.: Կաթու.→"
    "\"Catholic [Epistle]\", Ալէ.→\"Alleluia\", սաղ.→\"Psalm\", Աւետ.→\"Gospel\", "
    "մարգ.→\"Prophet\", Գծ.→\"Acts\", Առակ.→\"Proverbs\", ողջ.→\"Litany\", աղ.→\"Prayer\". "
    "When an abbreviation is a tone marker (ahf, ahg, Հմբ. / Hambartsi and similar), "
    "render it as the named tone/hymn and keep the transliterated name in [brackets].\n"
    "- RENDER scripture citations in standard English form: book chapter:verse(–verse), "
    "e.g. \"James 2:1\" … \"to verse 13\". Use the conventional English book name. When the "
    "Armenian psalm numbering differs from the English, give the Armenian number then the "
    "English in [brackets], e.g. \"Psalm 92 [93]\".\n"
    "- PRESERVE the line / item structure: one source item → one English line, in order. "
    "Keep section and service headers (e.g. \"In the Evening\", \"Midday Liturgy\") as their "
    "own lines.\n"
    "- Use [brackets] for any clarification you supply and for transliterated proper / tone / "
    "hymn names; you may also keep the original Armenian incipit in parentheses where helpful, "
    "matching the reference style.\n"
    "- Return ONLY the English translation — no preamble, no notes, no code fences."
)


def translate_page(page_text: str, cli_model: str) -> dict:
    """Translate one corrected Grabar page into English.

    ``page_text`` is the joined corrected text of the page (text lines only, in
    reading order — exactly the per-page block written to merged.md). Returns
    ``{text, in_tokens, out_tokens, cost, api_model, modelshort}``. Raises through
    ``lc``'s clients on API failure (including exhausted-credit errors) so the caller
    can stop and flag the user.
    """
    provider, api_model, short = lc.MODELS[cli_model]
    user = (
        "Translate this Classical Armenian (Grabar) liturgical page into English, "
        "following the rules. Preserve every item and its order.\n\n" + page_text
    )
    text, in_tok, out_tok = lc.CALL_FN[provider](api_model, TRANSLATE_SYSTEM, user)

    in_price, out_price = lc.PRICE_PER_MTOK[cli_model]
    cost = in_tok / 1e6 * in_price + out_tok / 1e6 * out_price
    return {
        "text": text,
        "in_tokens": in_tok,
        "out_tokens": out_tok,
        "cost": cost,
        "api_model": api_model,
        "modelshort": short,
    }
