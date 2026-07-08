# Topic Coverage — Hugging Face Spaces (Docker) image.
# Serves the FastAPI app + frontend on port 7860 (HF Spaces default).
FROM python:3.11-slim

# Build tools for hdbscan / umap-learn native extensions.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces run as uid 1000 — install + cache under a writable home.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface \
    TC_DB_PATH=/home/user/app/data/topic_coverage.db

WORKDIR /home/user/app

COPY --chown=user pyproject.toml README.md ./
COPY --chown=user backend ./backend
COPY --chown=user frontend ./frontend

# CPU-only torch first (avoids the multi-GB CUDA wheel), then the ML stack.
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --user -e ".[ml]"

# Pre-download the embedding model so the first analysis isn't slowed by it.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

EXPOSE 7860
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "7860"]
