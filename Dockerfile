FROM node:24-slim AS frontend-build

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim

ENV HOST=0.0.0.0 \
    PORT=7860 \
    PYTHONUNBUFFERED=1 \
    WORKFLOW_SEED_DIR=/app/workflows \
    WORKFLOWS_DIR=/app/data/workflows \
    STUDIO_DATA_DIR=/app/data \
    METADATA_DIR=/app/data/metadata \
    OUTPUTS_DIR=/app/data/outputs

WORKDIR /app

COPY . .

COPY --from=frontend-build /frontend/dist /app/frontend/dist

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils poppler-data \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r backend/requirements.txt

RUN mkdir -p /app/data/uploads /app/data/outputs /app/data/reports /app/data/workflows /app/data/metadata

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=3).read()"]

CMD ["python", "scripts/run_server.py"]
