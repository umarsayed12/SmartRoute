# Build React once, then serve its static output and the API from one non-root Python service.
FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_MODE=hosted \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 smartroute
COPY backend/app/ ./app/
COPY backend/scripts/prompts.jsonl ./scripts/prompts.jsonl
COPY --from=frontend /build/backend/static/ ./static/
USER smartroute
EXPOSE 10000
CMD ["python", "-m", "app.serve"]