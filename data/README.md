# `data/` layout and the method-tag convention

Every per-page **derived** artifact is tagged with the *method that produced it*,
so a hand-made and an automated run of the same page can coexist instead of
overwriting each other. The tag rides on the page id:

```
page_0487            base page id (page number only) — source PDF + render cache
page_0487_human      produced through the labeling UI (a person drew/accepted the boxes)
page_0487_auto       produced headlessly by data_prep.auto_slice (projection detector)
```

A page is **human** iff it has hand transcriptions under `data/lines`; otherwise
it is **auto**. The tag propagates through the whole derived tree:

```
data/columns/page_0487_auto_column_1.png            column crop
data/columns/boxes/page_0487_auto.json              committed column boxes (+ deskew angle)
data/lines/page_0487_auto/column_1/line_001.png     line crop (+ sibling .txt when transcribed)
data/predictions/<model_tag>/page_0487_auto/...      OCR / LLM-corrected text for those lines
```

A prediction path therefore reads end-to-end: *"`scale_500` model, run on the
`auto`-sliced lines of page 487."* `storage.page_artifact_id(n, method)` is the one
place this id is constructed; `page_id_for(n)` returns the base id (used only for the
method-independent deskew render cache in `data/_labeling_work/`).

## Prediction tags (`data/predictions/<tag>/`)

`<tag>` records how the **text** was produced (the slice method is already in the
page id underneath it):

| tag | meaning |
|---|---|
| `scale_500` | fine-tuned TrOCR (checkpoint `finetune_phase4_scale_500`), penalty-free beam-4. The OCR baseline. |
| `scale_500_llm_<model>_<mode>` | `scale_500` baseline post-corrected by an LLM. `<model>` ∈ {`gemini`, `opus`, `sonnet`, `gpt55`}; `<mode>` ∈ {`minimal-edit`, `rewrite`}. Written by `ml_vision/scripts/llm_correct.py`. |

`<mode>`: **minimal-edit** applies only tiny JSON-specified in-word letter swaps
(structurally caps over-correction); **rewrite** lets the model re-emit each line.

## Sets kept at their base names (not method-tagged) — by design

These are already unambiguous human / frozen sets, and nothing automated writes to
their paths, so tagging them would add churn with no separation benefit:

| path | what it is |
|---|---|
| `data/golden/` | original flat hand-labeled pages (`page_XXXX/line_NNN.{png,txt}`). Human ground truth. |
| `data/frozen_test_set/` | curated 100-line eval set + `manifest.json`. Its line-ids (e.g. `page_0451/line_016`) are **physical references into `data/phase4_dataset`** and are deliberately left at base page ids. |
| `data/phase4_dataset/` | flattened, renumbered training set (has a freeze marker; rebuilding renumbers and would break frozen ids). |
| `data/phase4_scaling/` | train-size scaling splits over `phase4_dataset`. |
| `data/pages/` | source one-page PDFs (`{n}.pdf`) — inputs, not derived. |
| `data/predictions/<tag>/frozen_test_set/` | predictions on the frozen eval set. |

## Migration

`data_prep/migrate_method_tags.py` performed the one-time rename to this convention
(dry-run by default; `--execute` to apply). Each run logs every move to
`data/backups/method_tag_migration_<ts>.json` for reversal. It is idempotent —
artifacts already ending in `_human`/`_auto` are skipped.
