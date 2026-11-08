"""Application configuration loaded from environment / .env file.

All settings have sane defaults so the app boots and runs in *mock* mode
without any API keys — ideal for a portfolio demo.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"

# Допустимый workspace_id: слаг без разделителей путей — исключает path
# traversal при формировании uploads/{workspace_id}/… (общий валидатор для
# config, dependency и будущих этапов).
WORKSPACE_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def validate_workspace_id(value: str) -> str:
    """Проверяет формат workspace_id; ValueError при нарушении.

    Не принимает None/пустую строку и запрещает разделители путей, `..`,
    заглавные буквы (в т.ч. как обход регистра).
    """
    if not value or not WORKSPACE_ID_RE.fullmatch(value):
        raise ValueError(
            f"workspace_id {value!r} не соответствует формату "
            "[a-z0-9_-]{1,64} (без разделителей путей)"
        )
    return value


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

    # --- Safety / resource limits (server-side, не доверяем клиенту) ---
    # Верхняя граница top_k из запроса. Продовый default 5, векторный поиск в
    # UI шлёт 10; 20 оставляет запас для больших корпусов и совпадает с
    # retrieval_candidates (пул кандидатов до rerank).
    chat_top_k_max: int = 20
    # Лимит размера загружаемого файла (МБ). 50 МБ согласованы с демо-сценарием
    # (User Guide: «файлы до 50 МБ») и покрывают документы типичного корпуса.
    max_upload_mb: int = 50
    # Бюджет токенов на блок CONTEXT в промпте. Текущий демо-корпус укладывается
    # в ~2–3k токенов (5 чанков); 3000 сохраняет текущее поведение и защищает
    # от раздувания промпта при top_k близком к капу или длинных чанках.
    chat_context_token_budget: int = 3000

    # --- Workspace isolation (Stage 4B) ---
    # Режим авторизации workspace. strict — по умолчанию: WORKSPACE_TOKENS
    # обязателен, иначе приложение не стартует (fail fast — отсутствие
    # конфигурации не может незаметно отключить авторизацию). demo — единый
    # workspace "default" без токена, для локального запуска и тестов
    # (тесты задают режим явно через env).
    workspace_auth_mode: Literal["strict", "demo"] = "strict"
    # Маппинг "token=workspace_id" через запятую. Значения токенов секретны:
    # не логируются, не попадают в тексты ошибок валидации и в repr/str
    # настроек (Field(repr=False)).
    workspace_tokens: str = Field(default="", repr=False)
    # Разобранный маппинг token → workspace_id (заполняется get_settings()
    # через parse_workspace_tokens; НЕ через pydantic-валидатор — ValidationError
    # сериализует входное значение и утечёт токены в лог старта).
    workspace_tokens_map: dict[str, str] = Field(default_factory=dict, repr=False)

    @field_validator("workspace_auth_mode", mode="before")
    @classmethod
    def _validate_auth_mode(cls, value: str) -> str:
        # Literal["strict","demo"] сам отсечёт неизвестные значения; здесь
        # только явное сообщение об ошибке конфигурации для лога старта.
        if value not in ("strict", "demo"):
            raise ValueError(
                f"WORKSPACE_AUTH_MODE={value!r} не поддерживается. "
                "Допустимые значения: strict, demo."
            )
        return value

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


def parse_workspace_tokens(mode: str, raw: str) -> dict[str, str]:
    """Разбирает WORKSPACE_TOKENS в маппинг token → workspace_id.

    Вызывается из get_settings() (не из pydantic-валидатора): собственный
    ValueError не сериализует входное значение, поэтому токены не утечут в
    лог старта. В сообщениях — только позиция записи и workspace_id.
    """
    if mode == "demo":
        return {}
    if not raw.strip():
        raise ValueError(
            "WORKSPACE_AUTH_MODE=strict требует непустой WORKSPACE_TOKENS "
            "в формате token=workspace_id,token=workspace_id"
        )
    mapping: dict[str, str] = {}
    seen_tokens: set[str] = set()
    for position, entry in enumerate(raw.split(","), start=1):
        entry = entry.strip()
        if not entry:
            raise ValueError(f"WORKSPACE_TOKENS: пустая запись на позиции {position}")
        if "=" not in entry:
            raise ValueError(
                f"WORKSPACE_TOKENS: запись на позиции {position} без '=' "
                "(формат token=workspace_id)"
            )
        token, _, workspace_id = entry.partition("=")
        token, workspace_id = token.strip(), workspace_id.strip()
        if not token:
            raise ValueError(f"WORKSPACE_TOKENS: пустой токен на позиции {position}")
        validate_workspace_id(workspace_id)  # ValueError с сообщением без токена
        if token in seen_tokens:
            raise ValueError(
                f"WORKSPACE_TOKENS: повторяющийся токен на позиции {position}"
            )
        seen_tokens.add(token)
        mapping[token] = workspace_id
    return mapping


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.workspace_tokens_map = parse_workspace_tokens(
        settings.workspace_auth_mode, settings.workspace_tokens
    )
    settings.ensure_dirs()
    return settings
