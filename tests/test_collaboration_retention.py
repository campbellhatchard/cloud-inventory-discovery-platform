from __future__ import annotations

import io
import zipfile


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "Collaboration Prospect") -> tuple[str, str, dict]:
    h = headers(me)
    prospect = client.post("/api/prospects", json={"name": name, "industry": "Distribution"}, headers=h)
    assert prospect.status_code == 200, prospect.text
    prospect_id = prospect.json()["id"]
    site = client.post(f"/api/prospects/{prospect_id}/sites", json={"name": "Main DC"}, headers=h)
    engagement = client.post(
        f"/api/prospects/{prospect_id}/engagements",
        json={"name": "Site survey", "site_id": site.json()["id"], "survey_date": "2026-07-30"},
        headers=h,
    )
    template = client.get("/api/report-templates").json()[0]
    report = client.post(
        f"/api/prospects/{prospect_id}/reports",
        json={
            "title": f"{name} Discovery",
            "engagement_id": engagement.json()["id"],
            "site_id": site.json()["id"],
            "report_template_id": template["id"],
        },
        headers=h,
    )
    assert report.status_code == 200, report.text
    payload = client.get(f"/api/reports/{report.json()['id']}").json()
    return prospect_id, report.json()["id"], payload


def test_optimistic_concurrency_assignment_comments_and_extraction(admin_session):
    client, me = admin_session
    h = headers(me)
    _, report_id, payload = create_report(client, me)
    section = next(item for item in payload["sections"] if item["process_module"] == "RECEIVING")

    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "First editor update", "expected_version": section["version"], "assigned_to_user_id": me["id"]},
        headers=h,
    )
    assert saved.status_code == 200, saved.text
    conflict = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Stale update", "expected_version": section["version"]},
        headers=h,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["current_narrative"] == "First editor update"

    comment = client.post(
        f"/api/reports/{report_id}/comments",
        json={"section_id": section["id"], "body": "Confirm the inbound exception process."},
        headers=h,
    )
    assert comment.status_code == 200
    resolved = client.post(f"/api/reports/{report_id}/comments/{comment.json()['id']}/resolve", headers=h)
    assert resolved.status_code == 200

    evidence = client.post(
        f"/api/reports/{report_id}/evidence",
        data={"section_id": section["id"], "caption": "Receiving procedure", "placement": "INLINE", "classification": "CONFIDENTIAL"},
        files={"file": ("receiving-notes.txt", b"PO receiving is recorded at the dock and reconciled at a desktop.", "text/plain")},
        headers=h,
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["extraction_state"] == "COMPLETED"
    reloaded = client.get(f"/api/reports/{report_id}").json()
    uploaded = next(item for item in reloaded["evidence"] if item["id"] == evidence.json()["id"])
    assert uploaded["has_extracted_text"] is True
    assert uploaded["extraction_state"] == "COMPLETED"


def test_capability_governance_promotes_controlled_knowledge(admin_session):
    client, me = admin_session
    h = headers(me)
    capabilities = client.get("/api/capabilities").json()
    proposed = next(item for item in capabilities if item["status"] == "PROPOSED")
    reviewed = client.post(
        f"/api/admin/capabilities/{proposed['id']}/review",
        json={"decision": "APPROVED", "note": "Product governance approval"},
        headers=h,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "APPROVED"
    knowledge = client.get("/api/admin/knowledge?approval_state=APPROVED").json()
    assert any(item["source_ref"] == f"capability:{proposed['capability_code']}" for item in knowledge)


def test_export_archive_and_permanent_delete(admin_session):
    client, me = admin_session
    h = headers(me)
    prospect_name = "Retention Export Prospect"
    prospect_id, report_id, _ = create_report(client, me, prospect_name)

    export = client.get(f"/api/prospects/{prospect_id}/export")
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        assert "manifest.json" in archive.namelist()
        assert "data/reports.json" in archive.namelist()

    archived = client.post(f"/api/prospects/{prospect_id}/archive", json={"reason": "Opportunity closed"}, headers=h)
    assert archived.status_code == 200
    assert archived.json()["status"] == "ARCHIVED"

    deleted = client.request(
        "DELETE",
        f"/api/admin/prospects/{prospect_id}",
        json={"confirm_name": prospect_name, "confirm_exported": True},
        headers=h,
    )
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/api/prospects/{prospect_id}").status_code == 404
    assert client.get(f"/api/reports/{report_id}").status_code == 404


def test_draft_report_can_be_permanently_deleted(admin_session):
    client, me = admin_session
    h = headers(me)
    prospect_id, report_id, payload = create_report(client, me, "Disposable Draft")
    deleted = client.request(
        "DELETE",
        f"/api/reports/{report_id}",
        json={"confirm_title": payload["report"]["title"]},
        headers=h,
    )
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/api/reports/{report_id}").status_code == 404
    workspace = client.get(f"/api/prospects/{prospect_id}").json()
    assert report_id not in {item["id"] for item in workspace["reports"]}


def test_ai_job_processing_is_asynchronous_and_human_reviewed(admin_session, monkeypatch):
    from sqlalchemy import select

    from app.ai_service import process_ai_job
    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, ReportSection, User

    client, me = admin_session
    _, report_id, payload = create_report(client, me, "Queued AI Prospect")
    section = next(item for item in payload["sections"] if item["process_module"] == "RECEIVING")

    def fake_run_ai(settings, context):
        assert context["purpose"] == "NARRATIVE"
        assert context["sections"][0]["id"] == section["id"]
        return {
            "summary": "Draft summary",
            "suggested_text": "Receiving currently depends on delayed desktop entry.",
            "gaps": [],
            "follow_up_questions": [],
            "capability_recommendations": [],
            "benefit_statements": [],
            "source_refs": [],
        }, {"input_tokens": 100, "output_tokens": 25}

    monkeypatch.setattr("app.ai_service.run_ai", fake_run_ai)
    settings = get_settings().model_copy(update={
        "ai_enabled": True,
        "ai_confidential_content_enabled": True,
        "openai_data_control_mode": "zero_data_retention",
        "openai_api_key": "test-key",
    })
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.id == me["id"]))
        job = AiJob(
            report_id=report_id,
            section_id=section["id"],
            purpose="NARRATIVE",
            instructions="Draft only from supplied evidence.",
            model=settings.openai_model,
            policy_decision={"allowed": True, "reason": "test", "mode": "zero_data_retention"},
            status="QUEUED",
            requested_by=actor.id,
        )
        db.add(job)
        db.commit()
        ai_job_id = job.id

        suggestion = process_ai_job(db, ai_job_id, settings)
        assert suggestion.review_state == "PENDING"
        processed = db.get(AiJob, ai_job_id)
        assert processed.status == "COMPLETED"
        assert processed.token_usage["output_tokens"] == 25
        assert db.scalar(select(AiSuggestion).where(AiSuggestion.ai_job_id == ai_job_id)).id == suggestion.id
        unchanged = db.get(ReportSection, section["id"])
        assert "Receiving currently depends" not in unchanged.narrative
