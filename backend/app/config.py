"""Application configuration loaded from environment / .env file.

All settings have sane defaults so the app boots and runs in *mock* mode
without any API keys — ideal for a portfolio demo.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "AI RAG Chat"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Storage paths ---
    data_dir: Path = DATA_DIR
    upload_dir: Path = DATA_DIR / "uploads"
    chroma_dir: Path = DATA_DIR / "chroma"
    database_url: str = f"sqlite:///{DATA_DIR / 'app.db'}"

    # --- Retrieval / chunking ---
    chunk_size: int = 800          # tokens
    chunk_overlap: int = 120       # tokens
    retrieval_top_k: int = 5
    embedding_provider: str = "local"          # "local" | "openai"
    local_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    openai_embedding_model: str = "text-embedding-3-small"

    # --- LLM provider keys (optional) ---
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    def ensure_dirs(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
