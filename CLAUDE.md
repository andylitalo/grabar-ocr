# Grabar OCR — Project Guide for Claude Code

## Project Goal
Digitize Classical Armenian (Grabar) texts written in Bolorgir script from scanned PDF books into a searchable, translated PostgreSQL database. Each record pairs an original line-crop image with its machine-transcribed Grabar text and an English translation produced by a frontier LLM (Claude 3.5 Sonnet or GPT-4o).

## Architecture in One Paragraph
Scanned PDFs live in Google Cloud Storage. An Apache Airflow DAG running on a local k3s cluster (Ubuntu server, Ryzen 9, RTX 3090) pulls batches of PDFs, uses `data_prep/` scripts (PyMuPDF + YOLOv8 + horizontal projection) to isolate and slice the Classical Armenian column into individual line images, then sends those images to a BentoML service serving a fine-tuned TrOCR model with adaptive GPU batching. The transcribed Grabar text is forwarded to the Anthropic/OpenAI API for translation, and the final payload is written to PostgreSQL. The developer connects from an M1 Pro MacBook via Tailscale VPN.

## Gated-Phase Development Model
All implementation is guided by phase documents in `docs/` (version-controlled — shared planning + findings). Each phase has a measurable **gate condition**. We do not write code for Phase N+1 until Phase N's gate is passed and its findings are recorded in the phase doc.

This matters because early phases test assumptions (e.g., "does off-the-shelf TrOCR work at all on Bolorgir?"). If an assumption fails, the next phase changes — often significantly. Building ahead of validation wastes effort and obscures where the real problem is.

**Current phase docs** (all phases: `docs/phase_*.md`; `docs/master_blueprint.md` is the original plan):
- `docs/phase_8_line_segmentation_survey.md` — done: the `paddle-filled` line baseline

**Workflow:** read the current phase doc before touching any code. Update the doc with findings before moving on.

## Repository Layout
```
data_prep/          Pre-processing: PDF → pages → column crops → line crops
ml_vision/          TrOCR fine-tuning, evaluation, BentoML model save
pipeline/           The pipeline that actually ships: modular crop→slice→ocr→correct→
                    translate orchestrator (see pipeline/README.md). Runs local on the
                    Mac; outputs to runs/<config-slug>/ (gitignored scratch).
corpus/             Productionized deliverable: the digitized + translated book,
                    per-page md + per-line json + manifest (committed). Built from the
                    blessed runs by `python -m pipeline.promote` (see corpus/README.md).
labeling_ui/        FastAPI app for human region-labeling / ground-truth (the crop=human path)
services/           BentoML OCR API, LLM translation client, DB writer
orchestration/      Airflow DAGs and custom GCS operators
infrastructure/     k3s bootstrap scripts, Helm chart overrides, k8s manifests
docs/               Phase planning docs + recorded findings (version-controlled)
data/               Data, apart from code: committed ground truth and outputs (column boxes,
                    blank markers, line-seg survey + reviews in data/lineseg_survey/); PDFs,
                    renders and crops stay ignored
```

> **What actually shipped vs. the original blueprint.** `README.md`/CLAUDE describe an
> aspirational cloud stack (Airflow on k3s, BentoML-served TrOCR, Postgres). That was never
> built — `services/`, `orchestration/`, and `infrastructure/` are empty/template stubs.
> The real, working pipeline is the local `pipeline/` package (Tesseract OCR + Gemini
> correction + Gemini translation), and the finished book lives in `corpus/`.

## Key Conventions
- Python 3.11+; type-annotate all function signatures; `pathlib.Path` over `os.path`
- BentoML is the only serving layer for ML models — do not use raw FastAPI for model endpoints
- Airflow DAGs use the TaskFlow API (`@task`) — no `BashOperator` for Python logic
- Secrets (GCS credentials, API keys, DB passwords) go in Kubernetes Secrets — never in code or git
- GPU device selection via `CUDA_VISIBLE_DEVICES` env var — no hardcoded device indices
- All training runs log to Weights & Biases; evaluation reports CER via `jiwer`

## Data storage
**Rule of thumb:** if a person wrote it, or it's small and stable, it goes in git. If a script
made it and it's big or will be remade, it goes outside git with a manifest.

- **In git:** ground truth and curated data: transcriptions, column boxes, blank markers,
  verified lines, survey reviews. Also small derived outputs that are expensive or can't be
  remade, such as nondeterministic, paid Gemini runs on the test set (`data/ocr_predictions/`,
  ~9 MB). Summary scores go in `reports/`.
- **Never in git:** PDFs, page renders, column and line crops (already ignored in
  `.gitignore`).
- **Machine-written files that are committed** get a `linguist-generated` entry in
  `.gitattributes`, so PR diffs stay reviewable. Add a pattern whenever a new committed
  output directory appears.
- **Separate PRs for code and data.** When a change produces large machine-written data
  (more than ~1,000 lines or ~1 MB of files marked `linguist-generated`), split it in two:
  1. **Code PR**, targeting `main`: the scripts, tests, docs and reports (summary scores),
     plus any small hand-made data. This is the PR that gets a real review.
  2. **Data PR**, stacked on the code PR: only the regenerated outputs. Its description
     says how to rebuild them: the exact command, and the code commit (SHA) it was run
     from. Review it for spot checks and size, not line by line.

  Merge the code PR first. Then retarget the data PR to `main` **before** deleting the
  code branch, because deleting the base branch closes the stacked PR. If the data is
  small, or a code change and its outputs only make sense together (for example a test
  fixture), one PR is fine.
- **Planned: the book-wide OCR run (after the Phase 9 layout review).** Its outputs, the full
  book times every engine and prompt version, go in GCS and are tracked with DVC (or GCS
  plus a committed manifest of path, sha256, settings and date), **not** committed to git.
  Rewriting large files on every iteration is what bloats history, and removing them later
  means rewriting history. Set this up before that run starts.
