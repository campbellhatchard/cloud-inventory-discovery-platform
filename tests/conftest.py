from __future__ import annotations

import os
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).parent / ".runtime"
TEST_ROOT.mkdir(parents=True, exist_ok=True)
DB_PATH = TEST_ROOT / "test.db"
STORAGE_PATH = TEST_ROOT / "storage"

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["LOCAL_STORAGE_ROOT"] = str(STORAGE_PATH)
os.environ["STORAGE_MODE"] = "local"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "Admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "Test-Initial-Password!2026"
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@test.invalid"
os.environ["AI_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database():
    if DB_PATH.exists():
        DB_PATH.unlink()
    if STORAGE_PATH.exists():
        import shutil
        shutil.rmtree(STORAGE_PATH)
    Base.metadata.create_all(bind=engine)
    get_settings.cache_clear()
    seed()
    yield
    engine.dispose()


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_session(client: TestClient) -> tuple[TestClient, dict]:
    login = client.post("/api/auth/login", json={"username": "Admin", "password": "Test-Initial-Password!2026"})
    if login.status_code == 401:
        login = client.post("/api/auth/login", json={"username": "Admin", "password": "Test-Replaced-Password!2026"})
    assert login.status_code == 200, login.text
    data = login.json()
    if data["force_password_change"]:
        changed = client.post(
            "/api/auth/change-password",
            json={"current_password": "Test-Initial-Password!2026", "new_password": "Test-Replaced-Password!2026"},
            headers={"X-CSRF-Token": data["csrf_token"]},
        )
        assert changed.status_code == 200, changed.text
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    return client, me.json()
