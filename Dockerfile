# DataLens AI: one container serving the API and the built web app.
# Build:  docker build -t datalens-ai .
# Run:    docker run -p 8000:8000 -e GEMINI_API_KEY=your-key datalens-ai   ->  http://localhost:8000

# ---- 1. Build the React frontend
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Python runtime
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/app backend/app
COPY backend/benchmarks backend/benchmarks
COPY sample-data sample-data
COPY --from=web /app/frontend/dist frontend/dist
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
WORKDIR /app/backend
ENV TRUST_PROXY=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/status')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
