"""Общие фикстуры: изолированное хранилище + TestClient.

env задаются ДО импорта app.* — settings кэшируются при первом обращении.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TEST_DATA = BASE / "data" / "test"

os.environ["UPLOAD_DIR"] = str(TEST_DATA / "uploads")
os.environ["CHROMA_DIR"] = str(TEST_DATA / "chroma")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATA / 'app.db'}"
# Гибрид включён — тестируем продовую конфигурацию.
os.environ["SEARCH_HYBRID"] = "1"
sys.path.insert(0, str(BASE))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def clean_store():
    shutil.rmtree(TEST_DATA, ignore_errors=True)
    TEST_DATA.mkdir(parents=True, exist_ok=True)
    get_settings().ensure_dirs()  # uploads/ после rmtree
    init_db()
    yield
    shutil.rmtree(TEST_DATA, ignore_errors=True)


@pytest.fixture(scope="session")
def client(clean_store):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def demo_loaded(client):
    """Загруженный демо-пак: нужен для поиска и чата."""
    r = client.post("/api/documents/demo")
    assert r.status_code == 201
    return r.json()
