# Grabar Digitization Pipeline

An end-to-end pipeline for digitizing Classical Armenian (Grabar) texts from scanned books into a searchable, translated PostgreSQL database.

## Pipeline Overview

```
GCS Raw PDFs
    │
    ▼
[data_prep] PyMuPDF → YOLOv8 layout detection → line crops
    │
    ▼
GCS Intermediate Images
    │
    ▼
[ml_vision] Fine-tuned TrOCR (BentoML / RTX 3090) → Grabar text
    │
    ▼
[services/translator_client] Claude 3.5 Sonnet / GPT-4o → English translation
    │
    ▼
[services/db_writer] PostgreSQL (k3s cluster)
```

All steps are orchestrated by **Apache Airflow** running on a local **k3s** Kubernetes cluster.

## Repository Structure

```
grabar-digitization-pipeline/
├── infrastructure/         # Kubernetes & server configs
│   ├── k3s_setup/          # Bootstrap scripts for the Ubuntu server
│   ├── helm_charts/        # Airflow, KServe, Postgres Helm values
│   └── manifests/          # PVCs, ConfigMaps, Secrets (gitignored)
├── orchestration/          # Apache Airflow
│   ├── dags/               # Pipeline DAG definitions (TaskFlow API)
│   ├── plugins/            # Custom operators (GCS ↔ local, etc.)
│   └── tests/              # DAG unit tests
├── ml_vision/              # TrOCR fine-tuning
│   ├── notebooks/          # Exploration & debugging
│   ├── scripts/            # Training & fine-tuning scripts
│   ├── evaluation/         # CER evaluation scripts
│   └── requirements.txt    # ML-specific deps (torch, transformers, bentoml)
├── data_prep/              # Pre-processing scripts
│   ├── pdf_slicer.py       # PDF → high-res images (PyMuPDF)
│   ├── layout_detector.py  # Column detection & deskew (YOLOv8)
│   └── line_cropper.py     # Column → single-line image crops
├── services/               # Serving & integration
│   ├── ocr_api/            # BentoML service wrapping fine-tuned TrOCR
│   ├── translator_client/  # Formats Grabar text & calls Claude/GPT-4o
│   └── db_writer/          # Writes final JSON payload to PostgreSQL
└── docs/                   # Local planning docs (gitignored)
```

## Quick Start

### Prerequisites
- Ubuntu server with NVIDIA GPU, k3s, and Tailscale installed
- `kubectl` and `helm` on your Mac
- GCS bucket and service account JSON (kept out of git)
- Python 3.11+

### 1. Bootstrap the Server
```bash
cd infrastructure/k3s_setup
bash install_k3s.sh
bash install_nvidia_plugin.sh
```

### 2. Fine-Tune TrOCR
```bash
cd ml_vision
pip install -r requirements.txt
python scripts/train.py --dataset /path/to/golden_dataset --output ./checkpoints
python evaluation/cer_eval.py --checkpoint ./checkpoints/best
```

### 3. Serve the Model
```bash
cd services/ocr_api
bentoml build
bentoml serve grabar_ocr_service:latest
```

### 4. Deploy Airflow
```bash
cd infrastructure/helm_charts
helm repo add apache-airflow https://airflow.apache.org
helm install airflow apache-airflow/airflow -f airflow-values.yaml
```

## First Three Steps (in order)

1. **Build the Golden Dataset** — manually crop and transcribe 50–100 pages of Bolorgir text. No code needed; this is the training foundation.
2. **Bootstrap the Server** — install Ubuntu, Tailscale, k3s, and the NVIDIA device plugin.
3. **Fine-Tune TrOCR** — prove the GPU can read Bolorgir with a low CER before building any orchestration.

## Hardware

| Role | Machine | Key Specs |
|------|---------|-----------|
| Dev / SSH | M1 Pro MacBook | 32GB RAM, 1TB SSD |
| Compute | Ubuntu Server | Ryzen 9, 128GB RAM, RTX 3090 24GB, 2TB NVMe |
| Storage | Google Cloud Storage | Raw PDFs + intermediate images |
| Translation | Anthropic / OpenAI API | Claude 3.5 Sonnet / GPT-4o |
