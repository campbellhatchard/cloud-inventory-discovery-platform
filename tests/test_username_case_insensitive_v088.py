from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.usernames import normalize_username


def _create_mixed_case_user(client: TestClient, me: dict, username: str = "MiXeD.User_88") -> dict:
    response = client.post(
        "/api/admin/users",
        json={
            "username": username,
            "email": f"{normalize_username(username).replace('.', '-').replace('_', '-')}@example.com",
            "display_name": "Mixed Case User",
            "password": "CasePass-123!",
            "roles": ["CONTRIBUTOR"],
        },
        headers={"X-CSRF-Token": me["csrf_token"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_username_capitalization_is_preserved_and_login_is_case_insensitive(admin_session) -> None:
    client, me = admin_session
    created = _create_mixed_case_user(client, me)
    assert created["username"] == "MiXeD.User_88"

    variants = ["MiXeD.User_88", "mixed.user_88", "MIXED.USER_88", "mIxEd.UsEr_88"]
    for variant in variants:
        with TestClient(app) as other:
            login = other.post("/api/auth/login", json={"username": variant, "password": "CasePass-123!"})
            assert login.status_code == 200, (variant, login.text)
            assert login.json()["username"] == "MiXeD.User_88"


def test_username_creation_and_login_trim_surrounding_whitespace(admin_session) -> None:
    client, me = admin_session
    created = _create_mixed_case_user(client, me, "  TrimmedUser88  ")
    assert created["username"] == "TrimmedUser88"
    with TestClient(app) as other:
        login = other.post("/api/auth/login", json={"username": "  trimmeduser88  ", "password": "CasePass-123!"})
        assert login.status_code == 200, login.text
        assert login.json()["username"] == "TrimmedUser88"


def test_case_variant_username_cannot_be_created_twice(admin_session) -> None:
    client, me = admin_session
    _create_mixed_case_user(client, me, "UniqueCaseUser88")
    duplicate = client.post(
        "/api/admin/users",
        json={
            "username": "uniquecaseuser88",
            "email": "different-case-user@example.com",
            "password": "CasePass-123!",
            "roles": ["CONTRIBUTOR"],
        },
        headers={"X-CSRF-Token": me["csrf_token"]},
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"] == "Username or email already exists."


def test_password_remains_case_sensitive(admin_session) -> None:
    client, me = admin_session
    _create_mixed_case_user(client, me, "PasswordCaseUser88")
    with TestClient(app) as other:
        rejected = other.post(
            "/api/auth/login",
            json={"username": "passwordcaseuser88", "password": "casepass-123!"},
        )
        assert rejected.status_code == 401


def test_v088_release_contract() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    config = (root / "app/config.py").read_text(encoding="utf-8")
    model = (root / "app/models.py").read_text(encoding="utf-8")
    auth = (root / "app/auth.py").read_text(encoding="utf-8")
    migration = (root / "alembic/versions/m83j6e2h0f43_case_insensitive_usernames.py").read_text(encoding="utf-8")
    ui = (root / "app/static/app.js").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.11"' in config
    assert "username_key" in model
    assert "User.username_key == normalize_username(username)" in auth
    assert 'down_revision = "l72i5d1g9e32"' in migration
    assert "case-insensitive username collision" in migration.lower()
    assert "Capitalization is preserved" in ui
    assert "Username sign-in is not case-sensitive" in ui
