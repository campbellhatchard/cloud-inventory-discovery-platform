from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def _new_workspace(client, me: dict) -> tuple[str, str]:
    onboard = client.post(
        "/api/prospects/onboard",
        json={
            "prospect": {"name": "v0.5 Usability Prospect"},
            "site": {"name": "Main Site", "timezone": "America/Denver"},
            "engagement": {"name": "Discovery"},
        },
        headers=headers(me),
    )
    assert onboard.status_code == 200, onboard.text
    prospect_id = onboard.json()["id"]
    templates = client.get("/api/report-templates").json()
    report = client.post(
        f"/api/prospects/{prospect_id}/reports",
        json={
            "title": "v0.5 Report",
            "engagement_id": onboard.json()["engagement_id"],
            "report_template_id": templates[0]["id"],
            "report_kind": "CAPTURE",
        },
        headers=headers(me),
    )
    assert report.status_code == 200, report.text
    return prospect_id, report.json()["id"]


def test_optional_questions_general_discussion_and_purpose_removed(admin_session) -> None:
    client, me = admin_session
    _, report_id = _new_workspace(client, me)
    report = client.get(f"/api/reports/{report_id}").json()
    titles = [section["title"] for section in report["sections"]]
    assert "General Discussion Points" in titles
    assert "Other" in titles
    assert "General Operational Observations" not in titles
    assert titles.index("Other") == titles.index("Manufacturing") + 1
    assert all(section["required_on_final"] is False for section in report["sections"])
    prompts = [prompt for items in report["prompts_by_module"].values() for prompt in items]
    assert prompts
    assert all(prompt["required_on_final"] is False for prompt in prompts)
    assert "What is the purpose and intended outcome of this section?" not in {prompt["question"] for prompt in prompts}


def test_empty_optional_sections_do_not_block_final_validation(admin_session) -> None:
    client, me = admin_session
    _, report_id = _new_workspace(client, me)
    result = client.post(f"/api/reports/{report_id}/validate", json={"final_requested": True}, headers=headers(me))
    assert result.status_code == 200, result.text
    codes = {item["code"] for item in result.json()["issues"]}
    assert "REQUIRED_SECTION_EMPTY" not in codes
    assert "REQUIRED_PROMPT_UNANSWERED" not in codes
    assert "SECTION_NOT_REVIEWED" not in codes


def test_report_level_status_controls_final_validation(admin_session) -> None:
    client, me = admin_session
    _, report_id = _new_workspace(client, me)
    payload = client.get(f"/api/reports/{report_id}").json()
    section = next(item for item in payload["sections"] if item["stable_key"] == "picking")
    update = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Picking currently uses a manual paper release.", "expected_version": section["version"]},
        headers=headers(me),
    )
    assert update.status_code == 200, update.text
    draft_validation = client.post(f"/api/reports/{report_id}/validate", json={"final_requested": True}, headers=headers(me))
    assert draft_validation.status_code == 200, draft_validation.text
    codes = {item["code"] for item in draft_validation.json()["issues"]}
    assert "SECTION_NOT_REVIEWED" not in codes
    assert "REPORT_NOT_READY" in codes
    status_update = client.patch(
        f"/api/reports/{report_id}",
        json={"state": "READY_FOR_REVIEW"},
        headers=headers(me),
    )
    assert status_update.status_code == 200, status_update.text
    final_validation = client.post(f"/api/reports/{report_id}/validate", json={"final_requested": True}, headers=headers(me))
    assert final_validation.status_code == 200, final_validation.text
    assert "REPORT_NOT_READY" not in {item["code"] for item in final_validation.json()["issues"]}


def test_prospect_logo_round_trip_uses_prospect_header_endpoint(admin_session) -> None:
    client, me = admin_session
    prospect_id, _ = _new_workspace(client, me)
    image = Image.new("RGB", (240, 120), "white")
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    uploaded = client.post(
        f"/api/prospects/{prospect_id}/logo",
        files={"file": ("prospect.png", payload.getvalue(), "image/png")},
        headers=headers(me),
    )
    assert uploaded.status_code == 200, uploaded.text
    workspace = client.get(f"/api/prospects/{prospect_id}").json()
    assert workspace["prospect"]["logo_url"] == f"/api/prospects/{prospect_id}/logo"
    logo = client.get(workspace["prospect"]["logo_url"])
    assert logo.status_code == 200
    assert logo.headers["content-type"].startswith("image/png")


def test_frontend_report_review_and_navigation_contract() -> None:
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    assert 'data-action="open-report-preview"' in app_js
    assert '<span>Report</span>' in app_js
    assert 'function reportPreviewContent()' in app_js
    assert 'Report Review' in app_js
    assert 'Generated Documents' in app_js
    assert 'function rememberReportNavScroll()' in app_js
    assert 'function restoreReportNavPosition(screenId)' in app_js
    assert 'data-action="upload-prospect-logo"' in app_js
    assert 'data-action="report-status"' in app_js
    assert '/draft.docx' in app_js
    assert '/draft.pdf' in app_js
    assert 'section-status' not in app_js
    assert 'section-assignee' not in app_js
    assert 'Required for final' not in app_js
    assert 'aria-label="Required"' not in app_js
    assert 'name="required_on_final"' not in app_js
    assert '.compiled-report' in styles
    assert '.prospect-logo' in styles
    assert '.report-status-control' in styles


def test_migration_contract_for_existing_reports() -> None:
    migration = (ROOT / "alembic" / "versions" / "f50a7c19d8e2_report_review_usability.py").read_text(encoding="utf-8")
    assert 'UPDATE report_sections SET required_on_final = false' in migration
    assert 'UPDATE prompt_definitions SET required_on_final = false' in migration
    assert "stable_key = 'purpose'" in migration
    assert "'general-discussion-points'" in migration
    assert 'op.add_column("prospects", sa.Column("logo_storage_key"' in migration
