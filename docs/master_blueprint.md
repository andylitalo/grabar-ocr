# Master Blueprint — Classical Armenian Digitization Pipeline

> This document is the living source of truth for the project. The verbatim architecture plan is preserved below, followed by a phase overview that will be refined as early phases complete and validate (or challenge) our assumptions.

---

## Part I — Original Architecture Plan (Verbatim)

### 1. The Hardware & Infrastructure Baseline
You are running a Hybrid Local-Cloud Architecture.
* The Command Center (Local Dev): M1 Pro MacBook (32GB RAM, 1TB SSD). You will use Cursor/Claude Code here to write all scripts, SSH into the server, and manage the cluster via Tailscale VPN.
* The Compute Engine (Local Server): Headless Ubuntu Linux Server (Ryzen 9 CPU, 128GB RAM, 1x NVIDIA RTX 3090 24GB or RTX 4080 Super 16GB, 2TB NVMe SSD). This runs your Kubernetes (k3s) cluster and executes heavy GPU workloads.
* The Cloud Layer: * Storage: Google Cloud Storage (GCS) for holding massive raw PDF scans and intermediate cropped images.
* Intelligence: OpenAI (GPT-4o) or Anthropic (Claude 3.5 Sonnet) APIs for the final translation step.

### 2. The Git Monorepo Structure
For a solo developer using AI coding assistants, a single repository (a "monorepo") is the easiest way to let Cursor index your entire project context.
Create a repository named grabar-digitization-pipeline and structure it like this:
```
grabar-digitization-pipeline/
├── infrastructure/ # Kubernetes & Server Configs
│ ├── k3s_setup/ # Scripts to bootstrap the server
│ ├── helm_charts/ # Configurations for Airflow, KServe, Postgres
│ └── manifests/ # Persistent Volume Claims, Secrets (API keys)
├── orchestration/ # Apache Airflow
│ ├── dags/ # The Python files that define your pipeline steps
│ ├── plugins/ # Custom Airflow operators (e.g., GCS to Local)
│ └── tests/ # Unit tests for your DAGs
├── ml_vision/ # TrOCR / Historical OCR Training
│ ├── notebooks/ # Jupyter notebooks for data exploration/testing
│ ├── scripts/ # PyTorch/HuggingFace training & fine-tuning scripts
│ ├── evaluation/ # Character Error Rate (CER) testing scripts
│ └── requirements.txt # Python dependencies for ML (torch, transformers)
├── data_prep/ # Pre-processing & Computer Vision
│ ├── pdf_slicer.py # PyMuPDF script to convert PDFs to high-res images
│ ├── layout_detector.py # YOLOv8 script to detect columns and deskew
│ └── line_cropper.py # Script to slice columns into single lines for TrOCR
├── services/ # Model Serving & API Integration
│ ├── ocr_api/ # FastAPI wrapper serving your fine-tuned TrOCR model
│ ├── translator_client/ # Script that formats and sends Grabar text to Claude/GPT-4
│ └── db_writer/ # Script to push final pairs to PostgreSQL
└── .cursorrules # Custom instructions for your Cursor IDE AI
```

### 3. The Service Interactions (The Pipeline Flow)
This is how a raw scanned book becomes a searchable, translated database entry.

**Phase 1: Ingestion & Pre-Processing (CPU Heavy)**
* Trigger: Apache Airflow runs a scheduled DAG (Directed Acyclic Graph) and pulls a batch of new raw PDFs from your Google Cloud Storage (GCS) "Raw Data" bucket.
* Slicing & Deskewing: Airflow triggers a Kubernetes pod running your data_prep scripts. It uses PyMuPDF to convert the PDF to images, straightens the page, and uses a lightweight layout-detection model to draw bounding boxes around the Classical Armenian columns, ignoring the English/Transliteration.
* Line Cropping: The script further slices those columns into horizontal images of single lines of text. These line-images are saved back to an "Intermediate Images" bucket in GCS.

**Phase 2: Historical Extraction (GPU Heavy)**
4. The OCR API: On your Linux server, KServe (or a standard Kubernetes deployment) is constantly running a pod that hosts your custom fine-tuned TrOCR model, with exclusive access to your RTX 3090 GPU. KServe exposes this model as a local API endpoint.
5. Transcription: Airflow pulls the single-line images from GCS and sends them to your local TrOCR endpoint. TrOCR reads the Bolorgir font, expands the pativ abbreviations using its language-model decoder, and returns raw, perfectly spelled Classical Armenian text.

**Phase 3: Cleanup & Translation (Cloud APIs)**
6. The Frontier Handoff: Airflow takes the assembled Grabar text paragraphs and constructs a strict prompt. It sends this prompt via API to Claude 3.5 Sonnet or GPT-4o.
7. The Output: The frontier model corrects any minor OCR spelling errors based on its contextual understanding of Apostolic theology, and outputs a formal, accurate English translation.

**Phase 4: Storage (Database)**
8. Commit: Airflow takes the final JSON payload—containing the original image link, the Grabar text, and the English translation—and writes it to a local PostgreSQL database running on your k3s cluster.
9. Cleanup: Airflow deletes the intermediate images to save storage and finishes the DAG run.

### 4. Your First 3 Steps to Execute
When you are ready to start building, do not build the whole pipeline at once. Follow this exact order:
* Build the "Golden Dataset" (No Code): Take 50-100 pages. Crop them into lines manually. Transcribe the Classical Armenian exactly as written. This is the foundation of everything; without this, you cannot train TrOCR or evaluate anything.
* Bootstrap the Server (Infrastructure): Install Ubuntu Server on your heavy machine. Install Tailscale on the server and your Mac. Install k3s and configure it to recognize your NVIDIA GPU using the NVIDIA device plugin.
* Fine-Tune TrOCR (The ML Core): Before installing Airflow, write a standard Python script on your server to fine-tune the base Hugging Face TrOCR model using your Golden Dataset. Prove that your GPU can learn to read the Bolorgir font and output text with a low Character Error Rate (CER).
Once step 3 works, the rest is just plumbing and orchestration.

### And BentoML
BentoML is the absolute perfect tool for your newly streamlined architecture. It is an open-source framework designed explicitly to take a trained machine learning model and instantly convert it into a production-ready API service.
While many developers default to wrapping their PyTorch models in standard web frameworks like FastAPI, BentoML is built to handle the unique, heavy-duty physics of machine learning that standard web servers ignore. (Interestingly, BentoML actually uses FastAPI internally to generate its high-performance asynchronous APIs, but it wraps it in ML-specific DevOps features).
Here is a breakdown of why BentoML is the ultimate "Platform Engineer" tool for your TrOCR serving layer, and exactly how it works.

**1. The Killer Features for Your Local Server**

*Runners & Hardware Isolation*
In a standard Python API, the web server (handling HTTP requests) and the ML model (crunching matrix multiplications) share the same process. This is a bottleneck. BentoML introduces a concept called "Runners". Runners physically isolate your model's prediction logic from the API interface. This means the web server handles incoming Airflow requests efficiently on your Ryzen CPU, while the Runner gets exclusive, optimized access to your RTX 3090 GPU to run the TrOCR inference.

*Adaptive Batching (The Throughput Multiplier)*
This is arguably BentoML's most powerful feature for your specific use case. When your Airflow worker slices a page of Classical Armenian into 40 individual line-images, sending them to the GPU one-by-one is highly inefficient. BentoML uses a dynamic dispatching mechanism called Adaptive Batching. It intelligently catches those incoming requests and groups them into a single batch before sending them to the GPU. It continuously adjusts the batch size and wait time based on real-time traffic, ensuring you maximize your GPU's throughput without sacrificing latency.

*Dependency Hell, Solved*
Machine learning models are notorious for dependency conflicts. BentoML solves this by using a bentofile.yaml configuration file where you explicitly declare all your required pip packages, Python versions, and system libraries.

**2. The Core Workflow (Building a "Bento")**
The entire philosophy of BentoML revolves around creating a standardized, version-controlled archive called a Bento (think of it like a Docker image, but specifically tailored for ML models).
Here is exactly how you will use it for your pipeline:
* Step 1: Save the Model: After your PyTorch script finishes fine-tuning TrOCR on your Grabar dataset, you use BentoML's API to save the model weights into the local BentoML Model Store.
* Step 2: Create the Service: You create a Python file (typically service.py) and use the @bentoml.service decorator to define a class. Inside this class, you write the logic that takes the incoming image, passes it to the Runner, and returns the extracted Grabar text.
* Step 3: Build the Bento: You run a simple command (bentoml build). The framework looks at your bentofile.yaml, gathers your service.py, and pulls the TrOCR weights from the Model Store, bundling them all together into a deployable Bento artifact.
* Step 4: Serve: You run bentoml serve. BentoML instantly provisions the optimal number of synchronous or asynchronous workers based on your CPU cores, fires up a Swagger UI so you can manually test the endpoint, and waits for Airflow to start sending it images.

By using BentoML, you get all the benefits of an enterprise-grade serving layer (metrics, tracing, batching, and GPU optimization) with about 50 lines of Python code, keeping your $5k architecture incredibly lean.

Since we have the ML serving layer figured out, how do you envision structuring the final PostgreSQL database to store these translations so your future mobile app can easily query them?

---

## Part II — Gated Phase Overview

> Phases 0 and 1 have full detail docs. Phases 2–6 are stubs — they will be fleshed out once Phase 0/1 results validate (or revise) our assumptions.

### Phase 0 — Micro Golden Dataset
**Doc:** `docs/phase_0_micro_golden_dataset.md`
Manually transcribe 1 page of Bolorgir-script text into line-crop + `.txt` pairs using the existing `data_prep/` automation for the image side. This takes 1–2 hours and is the prerequisite for every other phase.
**Gate:** All line crops for 1 page have verified `.txt` transcriptions.

### Phase 1 — Baseline OCR
**Doc:** `docs/phase_1_baseline_ocr.md`
Run off-the-shelf `microsoft/trocr-base-printed` on the Phase 0 crops on a Mac (no GPU needed). Measure CER with `jiwer`. Inspect failure modes. Record the number to beat.
**Gate:** CER is measured and documented. Any result passes.

### Phase 2 — Server Bootstrap
**Doc:** *(to be written after Phase 1)*
Install Ubuntu, k3s, NVIDIA device plugin, and Tailscale on the compute server. Verify GPU is visible to the cluster from the Mac.
**Gate:** `kubectl get nodes` shows 1 Ready node; test pod confirms `nvidia-smi`.

### Phase 3 — TrOCR Fine-Tuning
**Doc:** *(to be written after Phase 1)*
Fine-tune TrOCR on the Phase 0 micro dataset to prove the concept; expand dataset only if Phase 1 baseline warrants it. Target: measurably lower CER than Phase 1 baseline.
**Gate:** Held-out CER beats Phase 1 baseline by a meaningful margin (target defined after Phase 1).

### Phase 4 — BentoML Serving
**Doc:** *(to be written after Phase 3)*
Containerize the best checkpoint as a BentoML service with adaptive batching. Deploy to k3s. Verify endpoint with a manual `curl` test.
**Gate:** Line crop → Grabar text endpoint responds correctly; p99 latency < 500ms per batch.

### Phase 5 — Airflow Orchestration
**Doc:** *(to be written after Phase 4)*
Wire the full pipeline (GCS pull → data_prep → OCR → output) into an Airflow TaskFlow DAG. Deploy via Helm chart.
**Gate:** Full DAG run on a 5-page test PDF completes without errors; intermediate images cleaned up.

### Phase 6 — Translation & Storage
**Doc:** *(to be written after Phase 5)*
Add Claude 3.5 Sonnet translation step and PostgreSQL persistence. Finalize the schema for mobile app querying (full-text search on both Grabar and English columns, indexed by book + page + line).
**Gate:** End-to-end run produces rows in `translations` table; human spot-check of 10 translations passes theological accuracy review.
