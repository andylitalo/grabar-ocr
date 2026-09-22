# Grabar OCR Journey

## Issues in the Pipeline

- The column ordering got mixed up sometimes (e.g., Զ ordering of Saints days in volume 2).
I don't know how to fix this right now.
	- [] Verify that this was fixed with ordering scheme for the bounding boxes of all the regions
- Many lines seem cut off or garbled. Some of this is due to issues with cropping. Some is due to issues
with line slicing. Investigate and correct issues page-by-page, at least where there seem to be issues
with the translation.

## Issues in application

When applying the knowledge of the Տօնացոյց source text, the LLM often got confused because
the Տարեգիր or "year letter" is recorded for the Julian calendar but we need to apply to the
modern Gregorian calendar. I should make that a note with more prominence so the LLM never
misses it. It caused it to think that there was a serious discrepancy between the modern calendar
and the rubric in the Տոնացոյց in need of scholarly review when the issue was application of the
Julian calendar instead of the Gregorian.

Note: in general, Opus 4.8 tends to be a little quick in declaring an inconsistency between its
interpretation of the Տօնացոյց source text and the ground truth scraped from sacredtradition.am as
an unresolvable discrepancy between historical and modern calendars when the issue is its application
of the rubric, not an inherent inconsistency. Asking it to review the inconsistency and check if there
are other ways it might be consistent (such as if applying the Julian <> Gregorian mapping fixes it)
helped. Another example of this was its confident assertion that no taregirs celebrate Andrew/Adrian/Abraham
feast day in November, when in fact many do, but it had just not read those parts of the Տօնացոյց.

The LLM sometimes did not realize that there were two volumes and that both had been digitized by
the OCR pipeline. It would suggest waiting for this unknown First Volume that was not available
to it despite the text saying "First Volume" having been translated. This points to a need for
proper indexing and frontmatter to the translated text to improve discoverability by the LLM.

## Final Translation and Use for Lectionary

I was surprised by the quality of the final translation given the imperfections
of the upstream stages of the pipeline (cropping, line-slicing, OCR).
It read like a textbook and made sense. It seemed that Gemini-flash's ability
to compose sensible English filled in the gaps upstream.

I found when I provided the translated text to Claude Code to resolve the remain
ambiguities in the lectionary that Gemini-flash didn't correct all errors.
Specifically, it failed in two ways:

1. Non-English typos: page 593 August 5, there's a note describing an exception on a
particular type of leap year (ՂՁ), but the OCR hallucinated an additional letter Չ
(ՂՁՉ). Neither Gemini's character correction in the Grabar nor the Gemini-flash's
translation into English corrected the mistake. I suspect that since the year
lettering of the Armenian lectionary is well documented online, it didn't pick up
on this deviation from the pattern (single letter or two reverse-consecutive letters).
2. Formatting typos: because the crop was slightly off-center on page 574, some characters
from the other column were captured and OCR'd as margin notes. Gemini-flash didn't
have any context to know it was a formatting issue since it just got the raw, OCR'd
text. I would expect an agent reviewing the text to know that I've excluded margin
notes.

I plan to include these two as part of the agent's prompt to prevent them next time.

