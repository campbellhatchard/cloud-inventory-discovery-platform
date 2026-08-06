from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def jpeg_bytes() -> bytes:
    image = Image.new("RGB", (320, 240), "white")
    output = io.BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


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


def create_report(client, me, name: str) -> tuple[str, str, dict]:
    h = headers(me)
    prospect = client.post("/api/prospects", json={"name": name, "industry": "Distribution"}, headers=h)
    assert prospect.status_code == 200, prospect.text
    prospect_id = prospect.json()["id"]
    site = client.post(
        f"/api/prospects/{prospect_id}/sites",
        json={"name": "Warehouse", "timezone": "America/Chicago"},
        headers=h,
    )
    assert site.status_code == 200, site.text
    engagement = client.post(
        f"/api/prospects/{prospect_id}/engagements",
        json={"name": "Discovery", "site_id": site.json()["id"], "survey_date": "2026-08-04"},
        headers=h,
    )
    assert engagement.status_code == 200, engagement.text
    template = client.get("/api/report-templates").json()[0]
    report = client.post(
        f"/api/prospects/{prospect_id}/reports",
        json={
            "title": f"{name} Report",
            "engagement_id": engagement.json()["id"],
            "site_id": site.json()["id"],
            "report_template_id": template["id"],
        },
        headers=h,
    )
    assert report.status_code == 200, report.text
    return prospect_id, engagement.json()["id"], client.get(f"/api/reports/{report.json()['id']}").json()


def test_v086_version_migration_photo_retirement_and_speech_contract() -> None:
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    sw = (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")
    migration = (ROOT / "alembic" / "versions" / "k61h4c0f8d21_user_admin_photo_ai_retirement.py").read_text(encoding="utf-8")
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    ai_service = (ROOT / "app" / "ai_service.py").read_text(encoding="utf-8")
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.9"' in config
    assert 'version = "0.8.9"' in pyproject
    assert "ci-discovery-v0.8.9" in sw
    assert 'down_revision = "j50g3b9e7c10"' in migration
    assert 'op.drop_table("evidence_ai_observations")' in migration
    assert "PHOTO_ANALYSIS" not in worker
    assert "PHOTO_CONTEXT_REVISION" not in ai_service
    assert "input_image" not in ai_service
    assert "/photo-analysis" not in app_js
    assert "System / Browser Default" in app_js
    assert "speechSynthesis.getVoices()" in app_js
    assert "ci-discovery-speech-voice-uri" in app_js
    assert "ci-discovery-speech-rate" in app_js


def test_password_minimum_and_default_temporary_password_first_login(admin_session) -> None:
    from app.schemas import PasswordChangeRequest
    from pydantic import ValidationError

    try:
        PasswordChangeRequest(current_password="old", new_password="Ab1!short")
        raise AssertionError("9-character password should be rejected")
    except ValidationError:
        pass
    assert PasswordChangeRequest(current_password="old", new_password="Ab1!shortX").new_password == "Ab1!shortX"

    client, me = admin_session
    user = create_user(client, me, "v086firstlogin", ["CONTRIBUTOR"])
    with TestClient(app) as user_client:
        login = user_client.post("/api/auth/login", json={"username": user["username"], "password": "Test-Temporary1!"})
        assert login.status_code == 200, login.text
        assert login.json()["force_password_change"] is True
        blocked = user_client.get("/api/prospects")
        assert blocked.status_code == 428
        changed = user_client.post(
            "/api/auth/change-password",
            json={"current_password": "Test-Temporary1!", "new_password": "Changed1!X"},
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        )
        assert changed.status_code == 200, changed.text
        assert user_client.get("/api/prospects").status_code == 200


def test_admin_reset_revokes_sessions_and_restores_temporary_password(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import User

    client, me = admin_session
    user = create_user(client, me, "v086reset", ["CONTRIBUTOR"])
    with TestClient(app) as user_client:
        login = user_client.post("/api/auth/login", json={"username": user["username"], "password": "Test-Temporary1!"})
        assert login.status_code == 200, login.text
        changed = user_client.post(
            "/api/auth/change-password",
            json={"current_password": "Test-Temporary1!", "new_password": "BeforeReset1!"},
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        )
        assert changed.status_code == 200, changed.text
        assert user_client.get("/api/prospects").status_code == 200

        with SessionLocal() as db:
            target = db.get(User, user["id"])
            target.failed_login_count = 4
            db.commit()

        reset = client.post(f"/api/admin/users/{user['id']}/reset-password", headers=headers(me))
        assert reset.status_code == 200, reset.text
        assert user_client.get("/api/auth/me").status_code == 401

        relogin = user_client.post("/api/auth/login", json={"username": user["username"], "password": "Test-Temporary1!"})
        assert relogin.status_code == 200, relogin.text
        assert relogin.json()["force_password_change"] is True
        with SessionLocal() as db:
            target = db.get(User, user["id"])
            assert target.failed_login_count == 0
            assert target.locked_until is None


def test_v086_user_administration_is_superseded_by_reversible_v087_lifecycle(admin_session) -> None:
    client, me = admin_session
    user = create_user(client, me, "v086legacyuser", ["CONTRIBUTOR"])
    deleted = client.request(
        "DELETE",
        f"/api/admin/users/{user['id']}",
        json={"replacement_user_id": None},
        headers=headers(me),
    )
    assert deleted.status_code in {404, 405}

def test_photo_upload_remains_human_evidence_and_all_photo_ai_routes_are_gone(admin_session) -> None:
    client, me = admin_session
    h = headers(me)
    _, _, report_payload = create_report(client, me, "Photo Evidence Only")
    report_id = report_payload["report"]["id"]
    section = next(item for item in report_payload["sections"] if item["process_module"] == "RECEIVING")

    uploaded = client.post(
        f"/api/reports/{report_id}/evidence",
        data={"section_id": section["id"], "caption": "Receiving dock", "placement": "INLINE", "classification": "CONFIDENTIAL"},
        files={"file": ("dock.jpg", jpeg_bytes(), "image/jpeg")},
        headers=h,
    )
    assert uploaded.status_code == 200, uploaded.text
    evidence_id = uploaded.json()["id"]
    refreshed = client.get(f"/api/reports/{report_id}")
    assert refreshed.status_code == 200
    photo = next(item for item in refreshed.json()["evidence"] if item["id"] == evidence_id)
    assert photo["caption"] == "Receiving dock"
    assert "photo_analysis" not in photo

    retired = client.post(
        f"/api/reports/{report_id}/sections/{section['id']}/photo-analysis",
        json={"evidence_ids": [evidence_id]},
        headers=h,
    )
    assert retired.status_code in {404, 405}

    invalid_ai = client.post(
        f"/api/reports/{report_id}/ai",
        json={"section_id": section["id"], "purpose": "PHOTO_CONTEXT_REVISION", "evidence_ids": [evidence_id]},
        headers=h,
    )
    assert invalid_ai.status_code == 422
