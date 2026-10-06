# WHAT THIS FILE IS: the recipe Docker follows to build our IMAGE.
# An IMAGE is a frozen package: Linux + Python + our libraries + our code. A CONTAINER is one running copy of an image.
# Real example: "docker compose up --build" reads this file, builds image hcl-uc1-assistant:latest once,
# then starts TWO containers from it: "api" (FastAPI on port 8000) and "ui" (Streamlit on port 8501).
# Ollama (the local LLM) is NOT inside the image. It runs on the host laptop and the API reaches it
# at http://host.docker.internal:11434 (set in docker-compose.yml).
# Each line below is one build step. Docker caches steps, so a code change only re-runs the last few steps.
# API + UI image (same image, different command per service in docker-compose.yml)
# Start from the official small ("slim") Python 3.12 Linux image.
FROM python:3.12-slim

# ENV sets environment variables inside the image:
# PYTHONDONTWRITEBYTECODE=1 = no .pyc files. PYTHONUNBUFFERED=1 = logs appear at once.
# PIP_NO_CACHE_DIR=1 = pip keeps no download cache (smaller image). HF_HOME=/opt/hf = where the MiniLM model is saved.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/opt/hf
# All later commands run inside the /app folder of the image.
WORKDIR /app

# Install Linux system libraries. libgl1 + libglib2.0-0 are needed by OCR (reading scanned PDFs).
# curl is used by the healthcheck in docker-compose.yml. The last part deletes the package lists to save space.
# system libs needed by rapidocr/opencv (OCR of scanned PDFs)
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY requirements.txt first, then install. WHY: Docker caches this step, so editing our code later
# does not re-install every library. The extra index gives the CPU-only torch build (no GPU drivers, far smaller).
# rapidocr (OCR) and python-docx (read .docx files) are installed in the same step.
# CPU-only torch keeps the image small (no CUDA wheels); requirements are pinned
COPY requirements.txt .
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt \
        rapidocr-onnxruntime==1.4.4 python-docx

# Download the MiniLM embedding model during the build (saved under /opt/hf).
# HF_HUB_OFFLINE=1 then tells the library never to go online, so the container starts with no internet.
# bake the embedding model into the image so the container works offline
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
ENV HF_HUB_OFFLINE=1

# Copy the rest of the project (app/, ui/, scripts/, data/ ...) into /app. Files in .dockerignore are skipped.
COPY . .
# EXPOSE documents the ports the app listens on: 8000 = API, 8501 = Streamlit UI.
# A PORT is a numbered door on a computer that a server listens on.
EXPOSE 8000 8501
# Default start command: run the FastAPI app with uvicorn on port 8000.
# 0.0.0.0 = accept connections from outside the container, not only from inside it.
# The ui service in docker-compose.yml replaces this command with a Streamlit one.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
