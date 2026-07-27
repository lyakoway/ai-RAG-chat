FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept minimal; wheels cover pypdf/openpyxl/chromadb/fastembed.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app

# Persistent data (uploads, chroma index, sqlite) lives here — mount a volume.
VOLUME ["/app/data"]
EXPOSE 8000

# Shell form so ${PORT} (set by hosts like Render) is honored; 8000 locally.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
