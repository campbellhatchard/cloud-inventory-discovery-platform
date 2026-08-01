from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings
from app.storage import storage_configuration_error

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def _workspace(client, me: dict) -> tuple[str, str]:
    onboard = client.post(
        "/api/prospects/onboard",
        json={
            "prospect": {"name": "Collaborative v0.5.1 Prospect"},
            "site": {"name": "Main Site", "timezone": "America/Denver"},
            "engagement": {"name": "Discovery"},
        },
        headers=headers(me),
    )
    assert onboard.status_code == 200, onboard.text
    templates = client.get("/api/report-templates").json()
    created = client.post(
        f"/api/prospects/{onboard.json()['id']}/reports",
        json={
            "title": "Collaborative Draft Report",
            "engagement_id": onboard.json()["engagement_id"],
            "report_template_id": templates[0]["id"],
            "report_kind": "CAPTURE",
        },
        headers=headers(me),
    )
    assert created.status_code == 200, created.text
    return onboard.json()["id"], created.json()["id"]


def test_section_capture_no_longer_changes_section_status(admin_session) -> None:
    client, me = admin_session
    _, report_id = _workspace(client, me)
    report = client.get(f"/api/reports/{report_id}").json()
    section = next(item for item in report["sections"] if item["stable_key"] == "picking")
    assert section["state"] == "ACTIVE"
    assert "assigned_to_user_id" not in section
    prompt = report["prompts_by_module"]["PICKING"][0]
    saved = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/responses",
        json={"prompt_id": prompt["id"], "narrative": "Collaborative response"},
        headers=headers(me),
    )
    assert saved.status_code == 200, saved.text
    refreshed = client.get(f"/api/reports/{report_id}").json()
    updated = next(item for item in refreshed["sections"] if item["id"] == section["id"] )
    assert updated["state"] == "ACTIVE"


def test_draft_docx_download_does_not_require_r2(admin_session) -> None:
    client, me = admin_session
    _, report_id = _workspace(client, me)
    report = client.get(f"/api/reports/{report_id}").json()
    section = next(item for item in report["sections"] if item["stable_key"] == "picking")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Picking narrative for direct draft download.", "expected_version": section["version"]},
        headers=headers(me),
    )
    assert saved.status_code == 200, saved.text
    placeholder = Settings(
        environment="test",
        storage_mode="s3",
        s3_endpoint="https://<cloudflare-account-id>.r2.cloudflarestorage.com",
        s3_bucket="discovery-staging",
        s3_access_key_id="placeholder",
        s3_secret_access_key="placeholder",
    )
    client.app.dependency_overrides[get_settings] = lambda: placeholder
    try:
        downloaded = client.get(f"/api/reports/{report_id}/draft.docx")
        downloaded_pdf = client.get(f"/api/reports/{report_id}/draft.pdf")
    finally:
        client.app.dependency_overrides.pop(get_settings, None)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert downloaded.content.startswith(b"PK")
    assert downloaded_pdf.status_code == 200, downloaded_pdf.text
    assert downloaded_pdf.headers["content-type"].startswith("application/pdf")
    assert downloaded_pdf.content.startswith(b"%PDF")


def test_cloudflare_placeholder_is_reported_as_storage_configuration_error() -> None:
    settings = Settings(
        storage_mode="s3",
        s3_endpoint="https://<cloudflare-account-id>.r2.cloudflarestorage.com",
        s3_bucket="discovery-staging",
        s3_access_key_id="access",
        s3_secret_access_key="secret",
    )
    error = storage_configuration_error(settings)
    assert error is not None
    assert "placeholder" in error.lower()


def test_v051_migration_clears_assignment_and_section_workflow_state() -> None:
    migration = (ROOT / "alembic" / "versions" / "a61d9e7c4b10_collaborative_capture_report_status.py").read_text(encoding="utf-8")
    assert "assigned_to_user_id = NULL" in migration
    assert "state = 'ACTIVE' WHERE state <> 'REMOVED'" in migration
