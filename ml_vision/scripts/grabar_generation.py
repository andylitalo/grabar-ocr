"""
Shared generation utilities for Grabar TrOCR fine-tuning — and a hard-won lesson.

LESSON (2026-05-29): repetition penalties HURT a properly-trained TrOCR model.

The `աաաա` / `եեեե` degeneracy seen in the undertrained low-LR run was an
*undertraining* artifact, not something to suppress at generation time. On the
converged checkpoint, decoding the 34 training lines scores:

    plain greedy, no penalties .................. 0.064 CER   (gate < 0.10 PASSES)
    beam search (num_beams=4), no penalties ..... 0.026 CER
    repetition_penalty=1.3 + no_repeat_ngram=3 .. 0.322 CER
    + soft bigram penalty ....................... 0.454 CER

Real Grabar text legitimately reuses letters and short n-grams within a line, so
a global `repetition_penalty` (which discourages re-emitting ANY token already used
in the line) and `no_repeat_ngram_size` (which hard-bans recurring n-grams) knock
greedy decoding off the memorized sequence token by token. The penalties were also
distorting the per-epoch eval CER — the exact metric-distortion this debugging effort
exists to eliminate.

Default generation is therefore PENALTY-FREE (see `configure_generation`).
`SoftNoRepeatNGramLogitsProcessor` is retained ONLY as an opt-in escape hatch for
genuine degeneracy on unseen data; do not enable it by default. See
`reports/phase_3_converge_results.md`.
"""

from __future__ import annotations

import torch
from transformers import LogitsProcessor, LogitsProcessorList

# Beam search beats greedy on the converged model (0.026 vs 0.064 train CER).
# Used for final/inference generation; per-epoch eval stays greedy for speed.
NUM_BEAMS = 4


def configure_generation(model) -> None:
    """Penalty-free decoding config for a CONVERGED TrOCR model (see module lesson).

    Sets max_length and *explicitly* neutralizes repetition penalties so honest CER
    is not suppressed. Decoder-start / pad / eos token ids are set by the caller.
    """
    model.generation_config.max_length = 64
    model.generation_config.repetition_penalty = 1.0  # 1.0 == no penalty
    model.generation_config.no_repeat_ngram_size = 0  # 0 == disabled


class SoftNoRepeatNGramLogitsProcessor(LogitsProcessor):
    """Softly penalize tokens that would complete a previously-seen n-gram.

    OPT-IN ONLY. A graded counterpart to HuggingFace's hard ``no_repeat_ngram_size``:
    instead of forbidding the repeat (-inf), it scales the offending logit by
    ``penalty`` following the repetition-penalty convention (positive logits divided,
    negative multiplied), so ``penalty > 1.0`` discourages and ``1.0`` is a no-op.

    NOTE: this HURT the converged model (see module lesson). Kept only as an escape
    hatch for genuine degeneracy on unseen data — not part of the default recipe.
    """

    def __init__(self, ngram_size: int, penalty: float):
        if ngram_size < 1:
            raise ValueError("ngram_size must be >= 1")
        if penalty < 1.0:
            raise ValueError("penalty must be >= 1.0 (1.0 == no penalty)")
        self.ngram_size = ngram_size
        self.penalty = penalty

    def __call__(
        self, input_ids: torch.LongTensor, scores: torch.FloatTensor
    ) -> torch.FloatTensor:
        n = self.ngram_size
        cur_len = input_ids.shape[1]
        if cur_len < n:
            return scores
        for b in range(input_ids.shape[0]):
            seq = input_ids[b].tolist()
            prefix = tuple(seq[-(n - 1):]) if n > 1 else ()
            # Tokens that previously followed this same (n-1)-gram → would repeat an n-gram.
            banned = {
                seq[i + n - 1]
                for i in range(len(seq) - n + 1)
                if tuple(seq[i:i + n - 1]) == prefix
            }
            if not banned:
                continue
            idx = torch.tensor(sorted(banned), device=scores.device, dtype=torch.long)
            vals = scores[b, idx]
            scores[b, idx] = torch.where(vals > 0, vals / self.penalty, vals * self.penalty)
        return scores


def grabar_logits_processors(ngram_size: int = 2, penalty: float = 1.3) -> LogitsProcessorList:
    """OPT-IN soft n-gram repeat penalty (default: bigram, 1.3). Off by default — see
    module lesson; only use to tame genuine degeneracy on unseen data."""
    return LogitsProcessorList([SoftNoRepeatNGramLogitsProcessor(ngram_size, penalty)])
