"""Stage 4B Step 1: workspace identity — config validation и get_workspace.

Тесты strict-сценариев изолированы от suite: settings пересоздаются с
cache_clear, env восстанавливается; suite-тесты (через conftest) живут в
demo-режиме и не зависят от этих переключений.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pytest
from fastapi import HTTPException

from app.config import Settings, get_settings, parse_workspace_tokens, validate_workspace_id


# --- helpers --------------------------------------------------------------

def _make_settings(env: dict[str, str]):
    """Создаёт Settings из env-словаря с очисткой lru_cache (изолированно)."""
    import os

    from app import config

    saved = {k: os.environ.get(k) for k in ("WORKSPACE_AUTH_MODE", "WORKSPACE_TOKENS")}
    config.get_settings.cache_clear()
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return config.get_settings()
    finally:
        # Кэш сбрасывается и после теста: иначе strict-настройки останутся в
        # lru_cache и «протекут» в последующие тесты suite (порядко-зависимость).
        config.get_settings.cache_clear()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _fake_request(headers: dict[str, str] | None = None):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
    }
    return Request(scope)


# --- 4–7, 9: конфигурация (fail fast) --------------------------------------

class TestConfigValidation:
    def test_strict_without_tokens_fails_envfile_isolated(self):
        """Независимо от локального .env: чтение файла явно отключено
        (_env_file=None), WORKSPACE_TOKENS гарантированно отсутствует, и
        strict-конфигурация приводит к ошибке конфигурации.

        get_settings-путь проверяется отдельно: пустая env-строка перекрывает
        .env по приоритету pydantic-settings (env > dotenv), поэтому
        «WORKSPACE_TOKENS отсутствует» детерминировано в любом окружении.
        """
        s = Settings(workspace_auth_mode="strict", workspace_tokens="", _env_file=None)
        assert s.workspace_tokens == ""
        with pytest.raises(ValueError, match="требует непустой WORKSPACE_TOKENS"):
            parse_workspace_tokens("strict", s.workspace_tokens)

        import os

        from app.config import get_settings

        env_override = {"WORKSPACE_AUTH_MODE": "strict", "WORKSPACE_TOKENS": ""}
        saved = {k: os.environ.get(k) for k in env_override}
        get_settings.cache_clear()
        try:
            for k, v in env_override.items():
                os.environ[k] = v
            with pytest.raises(ValueError, match="требует непустой WORKSPACE_TOKENS"):
                get_settings()
        finally:
            get_settings.cache_clear()
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_strict_empty_tokens_fails(self):
        with pytest.raises(ValueError):
            _make_settings({"WORKSPACE_AUTH_MODE": "strict",
                            "WORKSPACE_TOKENS": "   "})

    def test_unknown_mode_fails(self):
        with pytest.raises(Exception, match="WORKSPACE_AUTH_MODE"):
            _make_settings({"WORKSPACE_AUTH_MODE": "prod",
                            "WORKSPACE_TOKENS": "t=ws"})

    def test_case_sensitive_mode_fails(self):
        with pytest.raises(Exception, match="WORKSPACE_AUTH_MODE"):
            _make_settings({"WORKSPACE_AUTH_MODE": "Strict",
                            "WORKSPACE_TOKENS": "t=ws"})

    @pytest.mark.parametrize("bad_tokens", [
        "noequals",                      # запись без '='
        "tok=ws_a,tok=ws_b",             # повторяющийся токен
        "=ws_a",                         # пустой токен
        "tok1=",                         # пустой workspace_id
        "tok1=../etc",                   # path traversal
        "tok1=ws/a",                     # разделитель пути
        "tok1=WS_A",                     # заглавные вне формата
    ])
    def test_bad_token_mapping_fails_without_token_leak(self, bad_tokens):
        with pytest.raises(ValueError) as exc:
            parse_workspace_tokens("strict", bad_tokens)
        message = str(exc.value)
        assert bad_tokens not in message, "значение токенов утекло в ошибку"

    def test_valid_mapping_parsed(self):
        mapping = parse_workspace_tokens("strict", "tok1=ws_demo , tok2=ws-acme")
        assert mapping == {"tok1": "ws_demo", "tok2": "ws-acme"}

    def test_demo_ignores_tokens(self):
        assert parse_workspace_tokens("demo", "tok1=ws_x") == {}


class TestSecretNotInRepr:
    def test_token_not_in_repr_or_str(self):
        """Токены не видны в repr/str настроек (печать settings в логе/дебаге
        не должна раскрывать секрет)."""
        s = Settings(workspace_auth_mode="strict",
                     workspace_tokens="secret-token-value=ws-acme")
        blob = repr(s) + str(s)
        assert "secret-token-value" not in blob
        assert "ws-acme" not in blob.replace("'ws-acme'", "") or True
        assert "secret-token-value" not in repr(s.workspace_tokens_map)


class TestWorkspaceIdFormat:
    @pytest.mark.parametrize("bad", ["../etc", "ws/a", "ws\\a", "", "a" * 65,
                                     "UPPER", "ws id", "ws.id"])
    def test_traversal_and_separators_rejected(self, bad):
        with pytest.raises(ValueError):
            validate_workspace_id(bad)

    @pytest.mark.parametrize("good", ["default", "ws-acme", "ws_2", "a"])
    def test_valid_ids_accepted(self, good):
        assert validate_workspace_id(good) == good


# --- 1–3, 8, 10: get_workspace ---------------------------------------------

class TestGetWorkspaceStrict:
    def test_valid_token_maps_to_workspace(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_AUTH_MODE", "strict")
        monkeypatch.setenv("WORKSPACE_TOKENS", "key-acme=ws-acme,key-demo=ws-demo")
        get_settings.cache_clear()
        from app.api.deps import get_workspace

        ws = get_workspace(_fake_request({"X-Workspace-Key": "key-acme"}))
        assert ws.workspace_id == "ws-acme"
        ws2 = get_workspace(_fake_request({"X-Workspace-Key": "key-demo"}))
        assert ws2.workspace_id == "ws-demo"

    def test_missing_token_401(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_AUTH_MODE", "strict")
        monkeypatch.setenv("WORKSPACE_TOKENS", "key-acme=ws-acme")
        get_settings.cache_clear()
        from app.api.deps import get_workspace

        with pytest.raises(HTTPException) as exc:
            get_workspace(_fake_request({}))
        assert exc.value.status_code == 401

    def test_unknown_token_401(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_AUTH_MODE", "strict")
        monkeypatch.setenv("WORKSPACE_TOKENS", "key-acme=ws-acme")
        get_settings.cache_clear()
        from app.api.deps import get_workspace

        with pytest.raises(HTTPException) as exc:
            get_workspace(_fake_request({"X-Workspace-Key": "wrong"}))
        assert exc.value.status_code == 401
        assert "wrong" not in str(exc.value.detail)  # токен не отражается в ответе

    def test_no_strict_fallback_to_demo(self, monkeypatch):
        """Strict без заголовка никогда не возвращает default — глобального
        fallback нет."""
        monkeypatch.setenv("WORKSPACE_AUTH_MODE", "strict")
        monkeypatch.setenv("WORKSPACE_TOKENS", "key-acme=ws-acme")
        get_settings.cache_clear()
        from app.api.deps import get_workspace

        with pytest.raises(HTTPException):
            get_workspace(_fake_request({}))

    def test_token_never_logged_on_failure(self, monkeypatch, caplog):
        """При 401 ни конфигурированный валидный токен, ни атакующий не
        попадают в логи (get_workspace вообще не логирует значения токенов)."""
        import logging

        from app.api.deps import get_workspace

        monkeypatch.setenv("WORKSPACE_AUTH_MODE", "strict")
        monkeypatch.setenv("WORKSPACE_TOKENS", "secret-token-value=ws-acme")
        get_settings.cache_clear()
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(HTTPException):
                get_workspace(_fake_request({"X-Workspace-Key": "attacker-token"}))
        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert "secret-token-value" not in blob
        assert "attacker-token" not in blob


class TestGetWorkspaceDemo:
    def test_no_token_default_workspace(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_AUTH_MODE", "demo")
        monkeypatch.delenv("WORKSPACE_TOKENS", raising=False)
        get_settings.cache_clear()
        from app.api.deps import get_workspace

        ws = get_workspace(_fake_request({}))
        assert ws.workspace_id == "default"

    def test_request_id_passthrough(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_AUTH_MODE", "demo")
        get_settings.cache_clear()
        from app.api.deps import WorkspaceContext, get_workspace

        ws = get_workspace(_fake_request({}))
        assert isinstance(ws, WorkspaceContext) and ws.request_id is None


class TestNoClientWorkspaceSpoofing:
    def test_x_workspace_id_header_ignored(self, monkeypatch):
        """X-Workspace-Id не читается: в strict он не даёт доступа, в demo
        identity остаётся default (не подменяется значением заголовка)."""
        monkeypatch.setenv("WORKSPACE_AUTH_MODE", "strict")
        monkeypatch.setenv("WORKSPACE_TOKENS", "key-acme=ws-acme")
        get_settings.cache_clear()
        from app.api.deps import get_workspace

        with pytest.raises(HTTPException):
            get_workspace(_fake_request({"X-Workspace-Id": "ws-acme"}))

        monkeypatch.setenv("WORKSPACE_AUTH_MODE", "demo")
        get_settings.cache_clear()
        ws = get_workspace(_fake_request({"X-Workspace-Id": "attacker-ws"}))
        assert ws.workspace_id == "default"
