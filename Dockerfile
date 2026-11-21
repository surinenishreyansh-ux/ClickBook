# syntax=docker/dockerfile:1
# ClickBook Production Multi-Architecture Dockerfile (linux/arm64 for OCI Ampere A1, linux/amd64)

# Stage 1: Build Frontend Assets
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend-builder
WORKDIR /site
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Backend Runtime
FROM python:3.12-slim AS production

# Set environment defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLICKBOOK_DATA=/app/data \
    FACE_MODEL_DIR=/app/models \
    CLICKBOOK_FRONTEND_DIST=/site \
    PORT=8000

WORKDIR /app

# Install system dependencies (OpenMP for OpenCV on ARM64/AMD64, curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source
COPY backend/ ./

# Pre-fetch official OpenCV Zoo YuNet & SFace neural network weights
RUN python models/download_models.py

# Copy compiled frontend from frontend-builder
COPY --from=frontend-builder /site/dist /site

# Create runtime directories and dedicated unprivileged user
RUN mkdir -p /app/data && \
    useradd -u 10001 -m -s /bin/bash clickbook && \
    chown -R clickbook:clickbook /app /site

USER clickbook

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --proxy-headers --forwarded-allow-ips='*'"]
