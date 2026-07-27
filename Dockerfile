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
RUN npm run build          # -> /fe/dist

# --- Backend + static frontend ---
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/app ./app
# FastAPI serves this at "/" (COPY forbids inline comments on the same line).
COPY --from=frontend /fe/dist ./static

# Persistent data (uploads, chroma, sqlite). Ephemeral without a mounted disk.
VOLUME ["/app/data"]
EXPOSE 8000

# Shell form so ${PORT} (set by Render) is honored; 8000 locally.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
