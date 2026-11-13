# Region-keyed data: plan for the book-wide OCR run

**Status:** planned, not built (maintainer, 2026-11-13) · **Blocked by:** the Phase 9 layout
review and the one-time `migrate repair` after it · **Do before:** the book-wide OCR run
(`docs/phase_11_ocr_comparison.md`, "Where this stands")

## Why

Today every crop, prediction, transcription and sample pick is keyed by a line's *name*:
a baseline key (`p520~line_013`) before the page is verified, a line id (`p520.013`)
after. Names change when a page is verified or re-verified, so `dev/line_review/migrate.py`
has to rename every file that uses them, judge which lines changed shape, and delete what
no longer fits. That code is the riskiest in the line-review tool (the PR #2 reviews found
data left behind or moved onto the wrong line).

The book-wide run multiplies the data (about 14k lines × every engine and prompt version,
stored in GCS with a manifest, where a rename is a copy), and a later layout model would
add a second layout of the same book. Both are simpler if the data is keyed by **what
was read**, the exact area of the page image, instead of by a name.

## The design

```
layouts/<layout_id>/page_520.json   the lines of one segmentation, in reading order:
                                    [{"id": "p520.013", "region": "p520/5ca6df5c851878ef", ...}]
regions                             region id -> {page, boundary}   (the boundary is in the
                                    layout files; a region is only an index over them)
crops/<region>.png                  one crop per region
predictions/<engine>.json           {"lines": {region: text}, "settings": ...}
transcriptions/<task>/page_520.json {region: {text, status, by, at, typed_as: "p520.013", prefill}}
```

- **Region id** = `p<page>/` + `transcribe.geometry(line)`: the sha256 of the boundary
  rounded to whole pixels, first 16 hex characters. Transcriptions already store this
  fingerprint as `geometry` (the shape they were typed against), so they convert with no
  loss. A region never changes and is never renamed.
- **Layout** = one complete segmentation of the book: the reviewed one (`review-2026`,
  today's `data/verified_lines/`), or a later model's. It owns reading order and line
  numbers, so `p520.013` is an attribute of a line in a layout, not a key of the data.
- **Data is looked up through the layout:** `layout.lines(page) -> [(id, region)]`, then by
  region. A line whose shape didn't change keeps its region, and its data is found with
  nothing moved. A reshaped, split or merged line has a new region with no data yet: it
  shows as untyped and un-OCR'd, which is what migrate does today by hand.
- **Correctors** (`corr-*`) read a whole page, but a line's own readings are their input,
  so their output is keyed by region like any engine's: an unchanged line keeps its
  correction when a neighbour changes, and a new region is corrected when it has none.
  Each correction also records the page's region list it was made with (the hash of its
  regions in reading order), so a later analysis can tell which corrections saw a different
  page; existing corrections are never replaced or deleted (maintainer, 2026-11-13: the
  scores must not move).
- **Nothing is overwritten.** The same line in two shapes is two regions and two crops;
  the same shape under two names (`p520~line_013` and `p520.013`) is one region.

Settle before building:

- **Hash input.** Hash the boundary in the coordinates the verified lines use (render
  pixels) and record the render's resolution in the layout file; if the renders are ever
  remade at another resolution, scale to the recorded one before hashing, or every region
  changes. The hash depends on the polygon's vertex order, which the materializer fixes;
  if that ever changes, version the id (`p520/g2:…`).
- **One-pixel edits** make a new region. That's correct (the crop changed); the prefill
  below carries a transcription over.
- **Unused regions** (from old shapes) stay in the files. They're small; prune them only if
  it ever matters, by dropping regions no kept layout uses.
- **Sample picks** say which line was sampled, so they need to follow an edited line:
  key them by region with `id` as an attribute, and map a pick on a retired region to its
  successor by overlap (as below). This is all that's left of `migrate.py`.

## Migration (one-time, at the start of the book-wide run)

Starting state: the layout review is done, `python -m dev.line_review.migrate repair` has
run (Phase 9, "After the gate"), and all data is keyed by line id.

1. **Score first.** `uv run python -m dev.ocr_eval.ceiling score`; keep
   `reports/phase11_ceiling.md` as the reference (v4 + `՚ի` rule: 95.0% on 160 lines as of
   2026-11-13).
2. **Give every verified line its region.** A script adds `region` to each line of
   `data/verified_lines/page_*.json` (computed from the boundary; no review), and
   `materialize.verified_record` writes it from then on. These files become layout
   `review-2026`.
3. **Convert the data, offline, rename only** (one script, one data commit):
   - **predictions** (`data/ocr_predictions/`, test set and ceiling): id → its line's region.
     `repair` already set aside predictions of lines whose shape changed (each file's
     `stale` section), so each remaining one is of its line's current region. Stale
     entries carry no shape, so they convert to `{old key: …}` history and stay unscored.
   - **transcriptions**: each record is keyed by its own `geometry`, not by the line's
     current one, and keeps the id as `typed_as`. A record typed on a shape edited since
     keeps its true region, so the current layout doesn't find it; it becomes a prefill
     candidate instead of a silent mismatch. Stale records (`stale/`) convert the same way.
   - **sample picks**: `{"region": …, "id": …}`.
   - **crops**: not converted; re-export them under region names (they cost nothing).
   - Refuse to finish if any key maps to no region or two keys map to one region with
     different values.
4. **Check the conversion.** Re-run the score through the new lookup: every number in the
   reference report must come out the same (same lines, same results). A difference means
   the conversion is wrong; nothing else changed.
5. **Switch the readers and writers.** Runners (`run_*.py`, `common.py`), `score.py`,
   `ceiling.py`, `correct.py` and the transcription endpoints look lines up through
   `layout.lines(page)` and read and write by region. The book-wide outputs go to GCS
   with a manifest of path, sha256, layout id, engine settings and date
   (CLAUDE.md, "Data storage").
6. **Retire the renaming in `migrate.py`.** Keep only the pick follow-up from step 3's
   design and the stale prefill below.

## Later: a new layout model (not built; the design keeps room for it)

A new segmenter's output becomes a second layout beside `review-2026`; its regions start
with no data. To carry transcriptions over:

- For each new region, find the old regions on the same page that overlap it strongly
  (polygon IoU with shapely, already a dependency; start around IoU ≥ 0.8, tuned on a few
  pages). Lines are horizontal bands, so most matches are clear.
- **One strong match:** copy its text into `prefill = {"source": <old region>, "iou": 0.93,
  "text": …}`, the field transcriptions already have, and show the line for a quick check.
- **Several old regions inside one new one** (a merge): join their texts in reading order
  as the prefill.
- **A split** (one old region over several new ones): no prefill; the lines are typed.
- The old layout and its data stay, so both layouts can be scored on the same lines
  before switching.

What this needs from today's data, and has: transcriptions keyed by region, each region's
boundary kept (in its layout file), and the `prefill` field.

## Fixes deferred from the PR #2 review (make them with step 5)

Step 5 rewrites the OCR tools anyway; these only matter once OCR runs again.

- **`correct.py` drift guard** accepts swapped or shifted lines that look alike (refrains,
  short codes such as `ԲՁ.`/`ԳՁ.`), and a reply with dropped and renumbered rows. Check the
  row numbers are exactly 1..N first (else align rows to lines by edit distance); flag
  only patterns (two rows each closer to the other's line, or a run of rows each matching
  the next line), not one near-match. Before adopting it, replay it over the accepted lines
  of every committed `corr-*` file and read each line it would reject. Save raw replies
  under `runs/` so later checks can replay them.
- **`correct.py` fallback pages:** a reply that is empty, truncated or in the wrong format
  is saved as all-Paddle "corrector output" and never retried. Keep the attempt with fewer
  fallbacks, record `fallback: [keys]` in the predictions file, leave a page with
  fallbacks undone so the next run retries it, and report fallback lines apart in the score.
- **Usage log:** count every billed call as it returns (including one that bills, then
  raises, such as a refusal), so a failed page still counts; write the log in a `finally`;
  count timed-out calls as `unmetered_calls`.
- **`ceiling.score`:** a paired bootstrap (one resample of the typed lines per iteration,
  every engine scored on it) instead of one shared random stream across engines; score the
  table on lines every engine covers and report coverage apart.
- **Empty replies** (`run_gemini.py`): raise instead of storing `""`, so the next run
  retries; record repeat failures as `failures: {key: reason}`, and count a missing line
  as wrong (or report coverage) in the score.
- **Locking:** a `fcntl.flock` shared by the runners and every writer of transcriptions,
  samples and predictions (with the in-process lock), and runners that merge their new
  lines into the file on disk instead of rewriting it from memory.
- **Transcribe page banner:** build its pool from every page with a verified file, so
  picks on a page back under review aren't listed as missing.
