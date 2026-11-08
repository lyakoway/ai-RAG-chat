"""FastAPI dependencies: trusted workspace identity (Stage 4B, Step 1).

workspace_id определяется ТОЛЬКО здесь, из доверенного backend-контекста:
- strict — заголовок X-Workspace-Key сопоставляется с WORKSPACE_TOKENS из
  настроек; отсутствующий/неизвестный токен → 401;
- demo — workspace "default" без токена (локальный запуск и тесты;
  тесты задают WORKSPACE_AUTH_MODE=demo явно).

X-Workspace-Id и workspace_id из body/query/DTO не читаются и игнорируются.
На этом шаге dependency к роутам не подключается (следующий шаг плана).
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.config import get_settings


@dataclass(frozen=True)
class WorkspaceContext:
    """Доверенная workspace-идентичность запроса.

    `request_id` — идентификатор из текущей архитектуры (генерируется в
    chat.py); dependency его не подменяет, если вызывающий код передаёт свой.
    """

    workspace_id: str
    request_id: str | None = None


def _header(request: Request, name: str) -> str | None:
    value = request.headers.get(name)
    return value.strip() if value and value.strip() else None


def get_workspace(request: Request) -> WorkspaceContext:
    """Trusted workspace identity (см. docs/STAGE_4B_PLAN.md §4).

    Режимы задаются в settings (WORKSPACE_AUTH_MODE / WORKSPACE_TOKENS);
    strict без конфигурации невозможен — Settings fail fast на старте.
    Значение токена никогда не логируется и не попадает в текст ошибки.

    ВРЕМЕННАЯ схема demo (задокументировано в docs/STAGE_4B_PLAN.md и
    docs/migration-plan.md): заголовок X-Workspace опционален и НЕ является
    auth — он лишь маркирует workspace до появления полноценной
    authentication. Любой клиент может подменить X-Workspace; enforcement
    появится вместе с auth (strict уже защищён токен-маппингом).
    """
    from app.config import get_settings, validate_workspace_id

    settings = get_settings()
    if settings.workspace_auth_mode == "demo":
        ws = _header(request, "X-Workspace")
        if not ws:
            return WorkspaceContext(workspace_id="default")
        try:
            validate_workspace_id(ws)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid X-Workspace header")
        return WorkspaceContext(workspace_id=ws)

    token = _header(request, "X-Workspace-Key")
    if not token:
        # Не раскрываем, был ли заголовок вообще: одна формулировка для
        # отсутствующего и неизвестного токена.
        raise HTTPException(status_code=401, detail="Invalid workspace key")
    workspace_id = settings.workspace_tokens_map.get(token)
    if workspace_id is None:
        raise HTTPException(status_code=401, detail="Invalid workspace key")
    return WorkspaceContext(workspace_id=workspace_id)


def get_scoped(db, model, obj_id: str, workspace_id: str):
    """Получение записи по id С обязательной проверкой workspace.

    Возвращает None для несуществующей И чужой записи — роуты отдают 404,
    чтобы не раскрывать существование (никогда не 403).
    """
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "workspace_id", None) != workspace_id:
        return None
    return obj
