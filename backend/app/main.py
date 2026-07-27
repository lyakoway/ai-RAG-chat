"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import chat, conversations, documents, models
from app.config import get_settings
from app.db.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(models.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


# Serve the built frontend when it is present (single-container deploy, e.g.
# Render). Mounted last so it never shadows the /api routes above. In local
# dev this dir is absent, so the API runs alone and Vite/nginx serves the UI.
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="frontend")
