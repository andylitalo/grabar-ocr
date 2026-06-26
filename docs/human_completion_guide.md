# Human completion guide — finishing pages the batch couldn't

The full-book pipeline (`pipeline.cli --range <lo>-<hi> --translate gemini`) digitizes
every page it can and **isolates** the ones it can't, listing them in each run's
`runs/<slug>/needs_human.md`. This guide explains how to finish those pages by hand.

Each batch leaves three kinds of page for a human, all surfaced in `needs_human.md`:

| Section | What it means | What to do |
| --- | --- | --- |
| **Deferred crops** | The headless column detector wasn't confident about the layout (a header band, a single column, or an odd/broken page). The page was **not** OCR'd. | Annotate its regions in the labeling UI (below), then re-run the page. |
| **Failed pages** | An isolated crop / OCR / API error during the batch. The run skipped past it and kept going. | Read the `reason`/`stage`, fix the underlying cause, then re-run the page. |
| **Needs labeling** | The page **was** digitized, but it has no ground-truth transcription, so CER couldn't be scored. | Optional — only needed if you want a measured CER for the page. Transcribe its lines in the UI. |

Everything below is **idempotent**: re-running a page that's already done reuses the
cached crops / OCR / correction / translation and spends ~$0. You can safely re-run a
whole range to fold finished pages back in.

---

## 1. Launch the labeling UI

From the repo root:

```bash
uv run python -m labeling_ui.app
```

Then open <http://127.0.0.1:8080/>. (State lives entirely on disk under `data/` — you
can stop and restart the server without losing anything.)

## 2. Select the page

Type the page number (e.g. `512` for `data/pages/512.pdf`) or step with **Prev / Next**.
A status badge shows `unlabeled` / `in_progress` / `done`. Click **Select this page**.

## 3. Draw the regions (for deferred / odd-layout / header pages)

The detector defers exactly the layouts a human is best at: headers over columns,
single columns, and odd pages. Instead of two fixed columns, a page is an **ordered
list of typed regions**, drawn top-to-bottom (and left-before-right within a band):

- **`header`** — a heading band spanning the full width above the columns.
- **`single`** — one full-width column of text.
- **`left`** / **`right`** — the two halves of a two-column band.

For each region draw **two nested boxes** and pick its **type**:

- **min** — the *tight inner* bound: just the real text ink, nothing else.
- **max** — the *loose outer* bound: out to (but just inside) the frame rule /
  column divider / page margin. The crop uses the **max** box; both are saved as
  gate truth.

Keep **Deskew** on unless the page is already perfectly straight. A plain two-column
page is `region_01_left` + `region_02_right`; a page with a heading is
`region_01_header` + `region_02_left` + `region_03_right`. Region order (`01`, `02`,
…) **is** the reading order. Click **Segment lines →** to slice each region into line
crops under `data/lines/page_XXXX_human/region_NN_<type>/`.

## 4. (Optional) transcribe the lines

Only needed for **needs-labeling** pages, or if you want measured CER. For each line
crop:

- Type the Grabar text and press **Enter** to submit + advance.
- **Empty** (Alt+E) for a blank line / section marker.
- **Reject** (Alt+R) for a cut-off or junk crop (it's moved aside, excluded from the
  dataset).
- Navigate with **Back / Next** (Alt+← / Alt+→) or click a pill to jump.

Line status is computed purely from the files: a `.png` with a non-empty sibling
`.txt` is labeled; empty `.txt` is an empty line; a crop under `rejected/` is excluded.

## 5. Fold the page back into the run

Once the page has region crops (and, for human pages, transcriptions), re-run just
that page through the same pipeline. Use `--crop human` if you annotated it by hand:

```bash
# odd-layout page you annotated in the UI:
.venv/bin/python -m pipeline.cli --pages 512 --crop human --translate gemini

# a page that merely failed transiently (re-use the auto cropper):
.venv/bin/python -m pipeline.cli --pages 512 --translate gemini
```

Because every stage is idempotent, this digitizes + translates the one page and leaves
the rest of the run untouched. Its Grabar lands in `runs/<slug>/pages/` and `merged.md`;
its English in `runs/<slug>/translations/gemini/`.

---

## Handling "Gemini credits exhausted"

If the batch prints `⛔ Gemini credits exhausted at page <X>`, it **stopped on
purpose** and left every page from `<X>` onward untouched. Refill credits, then re-run
the **exact same command** — it reuses everything already done (~$0) and resumes at
page `<X>`. Nothing is lost and nothing is paid for twice.

## Reference

- Region / method-tag convention: [`data/README.md`](../data/README.md)
- Labeling UI: [`labeling_ui/README.md`](../labeling_ui/README.md)
