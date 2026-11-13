# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    CAREERFLOW_CONFIG_DIR=/app/config \
    CAREERFLOW_DATA_DIR=/app/data \
    CAREERFLOW_OUTPUT_DIR=/app/output \
    CAREERFLOW_DB_PATH=/app/data/job_mark1.db

WORKDIR /app

RUN groupadd --gid 1000 careerflow \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin careerflow \
    && mkdir -p /app/config /app/data /app/output /app/frontend/dist \
    && chown -R careerflow:careerflow /app/config /app/data /app/output

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY pyproject.toml ./pyproject.toml
COPY backend/ ./backend/
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

USER 1000:1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"]
