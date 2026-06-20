# Grabar OCR — Project Guide for Claude Code

## Project Goal
Digitize Classical Armenian (Grabar) texts written in Bolorgir script from scanned PDF books into a searchable, translated PostgreSQL database. Each record pairs an original line-crop image with its machine-transcribed Grabar text and an English translation produced by a frontier LLM (Claude 3.5 Sonnet or GPT-4o).

## Architecture in One Paragraph
Scanned PDFs live in Google Cloud Storage. An Apache Airflow DAG running on a local k3s cluster (Ubuntu server, Ryzen 9, RTX 3090) pulls batches of PDFs, uses `data_prep/` scripts (PyMuPDF + YOLOv8 + horizontal projection) to isolate and slice the Classical Armenian column into individual line images, then sends those images to a BentoML service serving a fine-tuned TrOCR model with adaptive GPU batching. The transcribed Grabar text is forwarded to the Anthropic/OpenAI API for translation, and the final payload is written to PostgreSQL. The developer connects from an M1 Pro MacBook via Tailscale VPN.

## Gated-Phase Development Model
All implementation is guided by phase documents in `docs/` (version-controlled — shared planning + findings). Each phase has a measurable **gate condition**. We do not write code for Phase N+1 until Phase N's gate is passed and its findings are recorded in the phase doc.

This matters because early phases test assumptions (e.g., "does off-the-shelf TrOCR work at all on Bolorgir?"). If an assumption fails, the next phase changes — often significantly. Building ahead of validation wastes effort and obscures where the real problem is.

**Current phase docs:**
- `docs/phase_0_micro_golden_dataset.md` — build a 1-page ground-truth dataset (the prerequisite for everything)
- `docs/phase_1_baseline_ocr.md` — measure off-the-shelf TrOCR CER before any training
- `docs/master_blueprint.md` — full architecture blueprint + brief summaries of Phases 2–6

**Workflow:** read the current phase doc before touching any code. Update the doc with findings before moving on.

## Repository Layout
```
data_prep/          Pre-processing: PDF → pages → column crops → line crops
ml_vision/          TrOCR fine-tuning, evaluation, BentoML model save
services/           BentoML OCR API, LLM translation client, DB writer
orchestration/      Airflow DAGs and custom GCS operators
infrastructure/     k3s bootstrap scripts, Helm chart overrides, k8s manifests
docs/               Phase planning docs + recorded findings (version-controlled)
```

## Key Conventions
- Python 3.11+; type-annotate all function signatures; `pathlib.Path` over `os.path`
- BentoML is the only serving layer for ML models — do not use raw FastAPI for model endpoints
- Airflow DAGs use the TaskFlow API (`@task`) — no `BashOperator` for Python logic
- Secrets (GCS credentials, API keys, DB passwords) go in Kubernetes Secrets — never in code or git
- GPU device selection via `CUDA_VISIBLE_DEVICES` env var — no hardcoded device indices
- All training runs log to Weights & Biases; evaluation reports CER via `jiwer`
