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
    # Demo files shipped with the repo (backend/samples) for one-click loading.
    samples_dir: Path = BASE_DIR / "samples"

    # --- Retrieval / chunking ---
    chunk_size: int = 800          # tokens
    chunk_overlap: int = 120       # tokens
    retrieval_top_k: int = 5
    embedding_provider: str = "local"          # "local" | "openai"
    local_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    openai_embedding_model: str = "text-embedding-3-small"

    # --- Advanced retrieval (env: SEARCH_RERANK=1 включает реранк) ---
    # Гибрид (BM25 + вектора через RRF) включён по умолчанию: на двуязычном
    # демо-корпусе он вытягивает правильный документ из-под языкового «двойника»
    # (Recall@1 50% → 92%). Отключить: SEARCH_HYBRID=0.
    search_hybrid: bool = True
    search_rerank: bool = False     # cross-encoder rerank of fused candidates
    retrieval_candidates: int = 20  # candidate pool size before rerank
    rerank_model: str = "BAAI/bge-reranker-base"  # multilingual, local ONNX (~1 GB)

    # --- LLM provider keys (optional) ---
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    # Z.ai (Zhipu GLM) — OpenAI-совместимый эндпоинт, доступен без VPN.
    zai_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    # GLM-4.5/4.6 — «думающие» модели: рассуждения дают большую часть задержки
    # до первого токена (мы их не стримим). Отключены по умолчанию; включить:
    # ZAI_THINKING=enabled.
    zai_thinking: str = "disabled"
    # Number of layers to offload to GPU for Ollama. Leave None to let Ollama
    # decide. Set to 0 to force CPU (needed e.g. on macOS 13, where the GPU/Metal
    # build crashes with GGML_ASSERT).
    ollama_num_gpu: int | None = None

    def ensure_dirs(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
