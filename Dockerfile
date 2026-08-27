# Combined single-container image for one-service hosting (Render free tier).
# Builds the React frontend, then serves it from the FastAPI backend so the
# whole app lives on one origin — no cross-service networking, no CORS.
# Local dev still uses docker-compose with the separate backend/ + frontend/
# Dockerfiles; this file is used only for the single-service deploy.

# --- Frontend build ---
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Vite вшивает VITE_* на этапе сборки (как NEXT_PUBLIC_* в lyako-way).
ARG VITE_YANDEX_METRIKA_ID=
ARG VITE_GA4_MEASUREMENT_ID=
ENV VITE_YANDEX_METRIKA_ID=$VITE_YANDEX_METRIKA_ID \
    VITE_GA4_MEASUREMENT_ID=$VITE_GA4_MEASUREMENT_ID
RUN npm run build          # -> /fe/dist

# --- Backend + static frontend ---
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/app ./app
# Demo documents for the one-click loader (POST /api/documents/demo).
COPY backend/samples ./samples
# FastAPI serves this at "/" (COPY forbids inline comments on the same line).
COPY --from=frontend /fe/dist ./static

# Persistent data (uploads, chroma, sqlite). Ephemeral without a mounted disk.
VOLUME ["/app/data"]
# 7860 — порт по умолчанию для Hugging Face Spaces (совпадает с app_port в README).
EXPOSE 7860

# Shell form so ${PORT} (set by the host) is honored; 7860 by default.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}
