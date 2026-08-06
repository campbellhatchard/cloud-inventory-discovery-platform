from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_user(client, me, username: str, roles: list[str]) -> dict:
    response = client.post(
        "/api/admin/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "display_name": username.title(),
            "roles": roles,
        },
        headers=headers(me),
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_owned_report(client, me, target_id: str) -> tuple[str, str, str, str]:
    from app.database import SessionLocal
    from app.models import Engagement, ProspectMembership, Report, ReportSection

    h = headers(me)
    prospect = client.post("/api/prospects", json={"name": "Lifecycle Prospect", "industry": "Distribution"}, headers=h).json()
    site = client.post(f"/api/prospects/{prospect['id']}/sites", json={"name": "Warehouse", "timezone": "America/Chicago"}, headers=h).json()
    engagement = client.post(
        f"/api/prospects/{prospect['id']}/engagements",
        json={"name": "Discovery", "site_id": site["id"], "survey_date": "2026-08-04"},
        headers=h,
    ).json()
    template = client.get("/api/report-templates").json()[0]
    report = client.post(
        f"/api/prospects/{prospect['id']}/reports",
        json={"title": "Lifecycle Report", "engagement_id": engagement["id"], "site_id": site["id"], "report_template_id": template["id"]},
        headers=h,
    ).json()
    payload = client.get(f"/api/reports/{report['id']}").json()
    section_id = payload["sections"][0]["id"]
    with SessionLocal() as db:
        db.get(Report, report["id"]).owner_id = target_id
        db.get(Engagement, engagement["id"]).owner_id = target_id
        db.get(ReportSection, section_id).assigned_to_user_id = target_id
        if db.get(ProspectMembership, {"prospect_id": prospect["id"], "user_id": target_id}) is None:
            db.add(ProspectMembership(prospect_id=prospect["id"], user_id=target_id, role_scope="OWNER", created_by=me["id"]))
        db.commit()
    return prospect["id"], engagement["id"], report["id"], section_id


def test_v087_version_and_contract() -> None:
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    sw = (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")
    migration = (ROOT / "alembic" / "versions" / "l72i5d1g9e32_user_lifecycle_role_admin.py").read_text(encoding="utf-8")
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.10"' in config
    assert 'version = "0.8.10"' in pyproject
    assert "ci-discovery-v0.8.10" in sw
    assert 'down_revision = "k61h4c0f8d21"' in migration
    assert "SET status = 'INACTIVE' WHERE status = 'DELETED'" in migration
    assert 'router.put("/admin/users/{user_id}/roles"' in api
    assert 'router.patch("/admin/users/{user_id}/status"' in api
    assert 'router.delete("/admin/users/{user_id}"' not in api
    assert "Edit roles" in app_js
    assert "Deactivate" in app_js
    assert "Activate" in app_js
    assert "Delete user" not in app_js


def test_admin_can_change_user_roles(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import UserRole

    client, me = admin_session
    user = create_user(client, me, "v087roles", ["CONTRIBUTOR"])
    updated = client.put(
        f"/api/admin/users/{user['id']}/roles",
        json={"roles": ["CONTRIBUTOR", "REVIEWER", "OWNER"]},
        headers=headers(me),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["roles"] == ["CONTRIBUTOR", "OWNER", "REVIEWER"]
    with SessionLocal() as db:
        roles = set(db.scalars(select(UserRole.role).where(UserRole.user_id == user["id"])).all())
        assert roles == {"CONTRIBUTOR", "REVIEWER", "OWNER"}


def test_deactivate_preserves_roles_memberships_and_revokes_sessions(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import ProspectMembership, User, UserRole

    client, me = admin_session
    target = create_user(client, me, "v087inactive", ["CONTRIBUTOR", "REVIEWER"])
    h = headers(me)
    prospect = client.post("/api/prospects", json={"name": "Membership Preserve", "industry": "Distribution"}, headers=h).json()
    with SessionLocal() as db:
        db.add(ProspectMembership(prospect_id=prospect["id"], user_id=target["id"], role_scope="CONTRIBUTOR", created_by=me["id"]))
        db.commit()

    with TestClient(app) as user_client:
        login = user_client.post("/api/auth/login", json={"username": target["username"], "password": "Test-Temporary1!"})
        assert login.status_code == 200, login.text
        deactivated = client.patch(
            f"/api/admin/users/{target['id']}/status",
            json={"status": "INACTIVE", "replacement_user_id": None},
            headers=h,
        )
        assert deactivated.status_code == 200, deactivated.text
        assert user_client.get("/api/auth/me").status_code == 401
        assert user_client.post("/api/auth/login", json={"username": target["username"], "password": "Test-Temporary1!"}).status_code == 401

    with SessionLocal() as db:
        assert db.get(User, target["id"]).status == "INACTIVE"
        roles = set(db.scalars(select(UserRole.role).where(UserRole.user_id == target["id"])).all())
        assert roles == {"CONTRIBUTOR", "REVIEWER"}
        assert db.get(ProspectMembership, {"prospect_id": prospect["id"], "user_id": target["id"]}) is not None

    active_users = client.get("/api/users").json()
    assert target["id"] not in {item["id"] for item in active_users}
    admin_users = client.get("/api/admin/users").json()
    assert next(item for item in admin_users if item["id"] == target["id"])["status"] == "INACTIVE"


def test_reactivate_restores_login_with_preserved_roles(admin_session) -> None:
    client, me = admin_session
    target = create_user(client, me, "v087reactivate", ["CONTRIBUTOR", "REVIEWER"])
    h = headers(me)
    assert client.patch(f"/api/admin/users/{target['id']}/status", json={"status": "INACTIVE"}, headers=h).status_code == 200
    activated = client.patch(f"/api/admin/users/{target['id']}/status", json={"status": "ACTIVE"}, headers=h)
    assert activated.status_code == 200, activated.text
    with TestClient(app) as user_client:
        login = user_client.post("/api/auth/login", json={"username": target["username"], "password": "Test-Temporary1!"})
        assert login.status_code == 200, login.text
    admin_user = next(item for item in client.get("/api/admin/users").json() if item["id"] == target["id"])
    assert admin_user["roles"] == ["CONTRIBUTOR", "REVIEWER"]


def test_deactivating_owner_requires_replacement_and_preserves_roles(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import Engagement, ProspectMembership, Report, ReportSection, User, UserRole

    client, me = admin_session
    target = create_user(client, me, "v087owner", ["OWNER"])
    replacement = create_user(client, me, "v087replacement", ["OWNER"])
    prospect_id, engagement_id, report_id, section_id = create_owned_report(client, me, target["id"])
    h = headers(me)

    blocked = client.patch(f"/api/admin/users/{target['id']}/status", json={"status": "INACTIVE"}, headers=h)
    assert blocked.status_code == 409
    changed = client.patch(
        f"/api/admin/users/{target['id']}/status",
        json={"status": "INACTIVE", "replacement_user_id": replacement["id"]},
        headers=h,
    )
    assert changed.status_code == 200, changed.text
    with SessionLocal() as db:
        assert db.get(User, target["id"]).status == "INACTIVE"
        assert db.get(Report, report_id).owner_id == replacement["id"]
        assert db.get(Engagement, engagement_id).owner_id == replacement["id"]
        assert db.get(ReportSection, section_id).assigned_to_user_id == replacement["id"]
        assert db.get(ProspectMembership, {"prospect_id": prospect_id, "user_id": target["id"]}) is not None
        assert db.get(ProspectMembership, {"prospect_id": prospect_id, "user_id": replacement["id"]}) is not None
        roles = set(db.scalars(select(UserRole.role).where(UserRole.user_id == target["id"])).all())
        assert roles == {"OWNER"}


def test_last_admin_and_self_deactivation_are_protected(admin_session) -> None:
    client, me = admin_session
    h = headers(me)
    self_status = client.patch(f"/api/admin/users/{me['id']}/status", json={"status": "INACTIVE"}, headers=h)
    assert self_status.status_code == 400
    remove_self_admin = client.put(f"/api/admin/users/{me['id']}/roles", json={"roles": ["OWNER"]}, headers=h)
    assert remove_self_admin.status_code == 400
