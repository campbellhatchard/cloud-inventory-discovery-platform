from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path

from docx import Document


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "v0.8.1 Prospect") -> tuple[str, dict]:
    request_headers = headers(me)
    prospect = client.post(
        "/api/prospects",
        json={"name": name, "industry": "Distribution"},
        headers=request_headers,
    ).json()
    site = client.post(
        f"/api/prospects/{prospect['id']}/sites",
        json={"name": "Main DC"},
        headers=request_headers,
    ).json()
    engagement = client.post(
        f"/api/prospects/{prospect['id']}/engagements",
        json={"name": "Site walk", "site_id": site["id"], "survey_date": "2026-08-03"},
        headers=request_headers,
    ).json()
    template = client.get("/api/report-templates").json()[0]
    report = client.post(
        f"/api/prospects/{prospect['id']}/reports",
        json={
            "title": f"{name} Discovery",
            "engagement_id": engagement["id"],
            "site_id": site["id"],
            "report_template_id": template["id"],
        },
        headers=request_headers,
    ).json()
    return report["id"], client.get(f"/api/reports/{report['id']}").json()


def add_approved_solution_chain(client, me, report_id: str, payload: dict) -> tuple[dict, dict, dict]:
    request_headers = headers(me)
    section = next(item for item in payload["sections"] if item["process_module"] == "PICKING")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Picking priorities are communicated verbally during the shift.", "expected_version": section["version"]},
        headers=request_headers,
    )
    assert saved.status_code == 200, saved.text
    capability_response = client.post(
        "/api/admin/capabilities",
        json={
            "capability_code": f"V081-{report_id[-6:]}",
            "name": "Controlled mobile picking",
            "domain": "PICKING",
            "controlled_description": "Presents configured picking work to authorized mobile users.",
            "typical_prerequisites": "Configured items, locations, users, and source-system order release.",
            "limitations": "Does not create source-system customer orders.",
            "status": "APPROVED",
            "source": "v0.8.1 test catalog",
            "product_version": "Current SaaS release",
            "review_due_at": "2027-08-03T12:00:00Z",
        },
        headers=request_headers,
    )
    assert capability_response.status_code == 200, capability_response.text
    capability_id = capability_response.json()["id"]
    mapping_response = client.post(
        f"/api/reports/{report_id}/capability-mappings",
        json={
            "section_id": section["id"],
            "source_ref": "section:narrative",
            "capability_id": capability_id,
            "rationale": "Controlled mobile task presentation can support the observed picking workflow.",
        },
        headers=request_headers,
    )
    assert mapping_response.status_code == 200, mapping_response.text
    mapping_id = mapping_response.json()["id"]
    approved_mapping = client.post(
        f"/api/reports/{report_id}/capability-mappings/{mapping_id}/review",
        json={"decision": "APPROVED"},
        headers=request_headers,
    )
    assert approved_mapping.status_code == 200, approved_mapping.text
    solution = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/content",
        json={
            "content_type": "CLOUD_INVENTORY_APPROACH",
            "text": "Cloud Inventory can present configured picking work to mobile users while the ERP retains order ownership.",
            "expected_version": None,
        },
        headers=request_headers,
    )
    assert solution.status_code == 200, solution.text
    benefit_response = client.post(
        f"/api/reports/{report_id}/benefits",
        json={
            "section_id": section["id"],
            "capability_mapping_id": mapping_id,
            "statement": "Reduce reliance on verbal coordination when prioritizing picking work.",
            "category": "WORKFORCE_PRODUCTIVITY",
            "measure_type": "QUALITATIVE",
            "confidence": "HIGH",
        },
        headers=request_headers,
    )
    assert benefit_response.status_code == 200, benefit_response.text
    benefit_id = benefit_response.json()["id"]
    approved_benefit = client.post(
        f"/api/reports/{report_id}/benefits/{benefit_id}/review",
        json={"decision": "APPROVED"},
        headers=request_headers,
    )
    assert approved_benefit.status_code == 200, approved_benefit.text
    refreshed = client.get(f"/api/reports/{report_id}").json()
    section = next(item for item in refreshed["sections"] if item["id"] == section["id"])
    mapping = next(item for item in refreshed["capability_mappings"] if item["id"] == mapping_id)
    benefit = next(item for item in refreshed["benefits"] if item["id"] == benefit_id)
    return section, mapping, benefit


def test_manual_executive_summary_is_versioned_and_conflict_safe(admin_session):
    client, me = admin_session
    report_id, _ = create_report(client, me, "Executive Summary Versions")
    first = client.put(
        f"/api/reports/{report_id}/content",
        json={"content_type": "EXECUTIVE_SUMMARY", "text": "Initial executive summary.", "expected_version": None},
        headers=headers(me),
    )
    assert first.status_code == 200, first.text
    second = client.put(
        f"/api/reports/{report_id}/content",
        json={"content_type": "EXECUTIVE_SUMMARY", "text": "Revised executive summary.", "expected_version": first.json()["version"]},
        headers=headers(me),
    )
    assert second.status_code == 200, second.text
    stale = client.put(
        f"/api/reports/{report_id}/content",
        json={"content_type": "EXECUTIVE_SUMMARY", "text": "Stale edit.", "expected_version": first.json()["version"]},
        headers=headers(me),
    )
    assert stale.status_code == 409
    versions = client.get(f"/api/reports/{report_id}/content-versions?content_type=EXECUTIVE_SUMMARY").json()
    assert [item["version"] for item in versions[:2]] == [2, 1]
    assert versions[0]["is_current"] is True
    assert versions[1]["is_current"] is False


def test_ai_executive_summary_acceptance_creates_current_report_content(admin_session):
    from app.ai_service import build_executive_summary_snapshot
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, Report

    client, me = admin_session
    report_id, report = create_report(client, me, "AI Executive Summary")
    add_approved_solution_chain(client, me, report_id, report)
    refreshed = client.get(f"/api/reports/{report_id}").json()
    with SessionLocal() as db:
        model = db.get(Report, report_id)
        snapshot = build_executive_summary_snapshot(db, model)
        job = AiJob(
            report_id=report_id,
            purpose="EXECUTIVE_SUMMARY",
            model="test-model",
            policy_decision={"allowed": True},
            context_snapshot=snapshot,
            status="COMPLETED",
            requested_by=me["id"],
        )
        db.add(job)
        db.flush()
        suggestion = AiSuggestion(
            ai_job_id=job.id,
            report_id=report_id,
            purpose="EXECUTIVE_SUMMARY",
            content={
                "summary_text": "The discovery identified verbally coordinated picking priorities. Cloud Inventory can support controlled mobile task presentation while the ERP retains order ownership.",
                "verification_status": "PASSED",
                "accept_allowed": True,
                "source_report_revision": refreshed["report"]["revision"],
                "source_refs": [{"ref": "section:narrative", "label": "Picking current operations"}],
            },
            source_refs=[],
            confidence="HIGH",
            review_state="PENDING",
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id
    accepted = client.post(
        f"/api/reports/{report_id}/ai-suggestions/{suggestion_id}/review",
        json={"decision": "APPROVED"},
        headers=headers(me),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["applied"]["executive_summary"] is True
    payload = client.get(f"/api/reports/{report_id}").json()
    assert payload["executive_summary"]["source_type"] == "AI_ACCEPTED"
    assert "verbally coordinated" in payload["executive_summary"]["text"]


def test_readiness_dashboard_uses_actual_content_chain(admin_session):
    client, me = admin_session
    report_id, report = create_report(client, me, "Readiness")
    initial = client.get(f"/api/reports/{report_id}/readiness").json()
    picking_initial = next(item for item in initial["sections"] if item["process_module"] == "PICKING")
    assert picking_initial["status"] == "MISSING"
    section, _, _ = add_approved_solution_chain(client, me, report_id, report)
    ready = client.get(f"/api/reports/{report_id}/readiness").json()
    picking = next(item for item in ready["sections"] if item["section_id"] == section["id"])
    assert picking["status"] == "READY"
    assert picking["approved_mapping_count"] == 1
    assert picking["approved_benefit_count"] == 1


def test_review_queue_and_traceability_are_source_aware(admin_session):
    client, me = admin_session
    report_id, report = create_report(client, me, "Queue and Traceability")
    section = next(item for item in report["sections"] if item["process_module"] == "PICKING")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Operators use printed pick lists.", "expected_version": section["version"]},
        headers=headers(me),
    )
    assert saved.status_code == 200
    comment = client.post(
        f"/api/reports/{report_id}/comments",
        json={"section_id": section["id"], "body": "Confirm how urgent work is identified."},
        headers=headers(me),
    )
    assert comment.status_code == 200
    queue = client.get(f"/api/reports/{report_id}/review-queue").json()
    assert any(item["type"] == "COMMENT" and item["section_id"] == section["id"] for item in queue["items"])
    traceability = client.get(f"/api/reports/{report_id}/traceability").json()
    picking = next(item for item in traceability["sections"] if item["section_id"] == section["id"])
    assert any(item["classification"] == "DIRECT_OBSERVATION" for item in picking["claims"])


def test_report_quality_suggestion_is_available_in_review_queue(admin_session):
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion

    client, me = admin_session
    report_id, report = create_report(client, me, "Quality Review")
    section = next(item for item in report["sections"] if item["process_module"] == "PICKING")
    with SessionLocal() as db:
        job = AiJob(
            report_id=report_id,
            purpose="REPORT_QUALITY_REVIEW",
            model="test-model",
            policy_decision={"allowed": True},
            context_snapshot={},
            status="COMPLETED",
            requested_by=me["id"],
        )
        db.add(job)
        db.flush()
        suggestion = AiSuggestion(
            ai_job_id=job.id,
            report_id=report_id,
            purpose="REPORT_QUALITY_REVIEW",
            content={
                "overall_assessment": "Additional solution coverage is required.",
                "issues": [{"category": "MISSING_COVERAGE", "severity": "MEDIUM", "section_id": section["id"], "message": "Picking has no solution approach.", "recommendation": "Add an approved approach.", "source_refs": []}],
                "source_report_revision": report["report"]["revision"],
                "verification_status": "PASSED",
            },
            source_refs=[],
            confidence="HIGH",
            review_state="PENDING",
        )
        db.add(suggestion)
        db.commit()
    payload = client.get(f"/api/reports/{report_id}").json()
    assert payload["quality_review"]["content"]["overall_assessment"].startswith("Additional")
    assert any(item["type"] == "QUALITY_ISSUE" for item in payload["review_queue"]["items"])
    reviewed = client.post(
        f"/api/reports/{report_id}/ai-suggestions/{payload['quality_review']['id']}/review",
        json={"decision": "APPROVED"},
        headers=headers(me),
    )
    assert reviewed.status_code == 200, reviewed.text
    queue = client.get(f"/api/reports/{report_id}/review-queue").json()
    assert not any(item["type"] == "QUALITY_ISSUE" for item in queue["items"])


def test_admin_operations_exposes_safe_heartbeat_and_lifecycle(admin_session):
    from app.database import SessionLocal
    from app.models import WorkerHeartbeat, utcnow

    client, _ = admin_session
    with SessionLocal() as db:
        heartbeat = db.get(WorkerHeartbeat, "worker")
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(
                component="worker",
                app_version="0.8.1",
                status="HEALTHY",
                storage_configured=True,
                details={"worker_id": "test-worker"},
                last_seen_at=utcnow() - timedelta(seconds=10),
            )
            db.add(heartbeat)
        else:
            heartbeat.status = "HEALTHY"
            heartbeat.storage_configured = True
            heartbeat.details = {"worker_id": "test-worker"}
            heartbeat.last_seen_at = utcnow() - timedelta(seconds=10)
        db.commit()
    response = client.get("/api/admin/operations")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["worker"]["status"] == "HEALTHY"
    serialized = response.text.lower()
    assert "secret_access_key" not in serialized
    assert "openai_api_key" not in serialized


def test_full_discovery_document_includes_executive_summary(admin_session):
    from app.config import get_settings
    from app.database import SessionLocal
    from app.documents import generate_docx

    client, me = admin_session
    report_id, _ = create_report(client, me, "Executive Summary Document")
    saved = client.put(
        f"/api/reports/{report_id}/content",
        json={"content_type": "EXECUTIVE_SUMMARY", "text": "This is the governed executive summary for the discovery report.", "expected_version": None},
        headers=headers(me),
    )
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        data = generate_docx(db, report_id, get_settings(), publication_type="FULL_DISCOVERY", is_final=False)
    document = Document(io.BytesIO(data))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Executive Summary" in text
    assert "governed executive summary" in text


def test_v081_frontend_and_release_markers_are_present():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app/static/app.js").read_text(encoding="utf-8")
    models = (root / "app/models.py").read_text(encoding="utf-8")
    migration = root / "alembic/versions/f16c9d5a3e66_report_quality_readiness_governance.py"
    assert "Review Entire Report" in app_js
    assert "executive-summary-editor" in app_js
    assert "Central Reviewer Work Queue" in app_js
    assert "AI, Worker, Storage, and Publication Health" in app_js
    assert "class ReportContentVersion" in models
    assert "class WorkerHeartbeat" in models
    assert migration.exists()


def test_expired_knowledge_is_excluded_from_solution_ai_grounding(admin_session):
    from app.ai_service import build_solution_snapshot
    from app.database import SessionLocal
    from app.models import KnowledgeEntry, Report, ReportSection, utcnow

    client, me = admin_session
    report_id, report = create_report(client, me, "Expired Knowledge")
    section = next(item for item in report["sections"] if item["process_module"] == "PICKING")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Picking work is presented on printed lists.", "expected_version": section["version"]},
        headers=headers(me),
    )
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        model = db.get(Report, report_id)
        section_model = db.get(ReportSection, section["id"])
        expired = KnowledgeEntry(
            source_type="INTERNAL_REFERENCE",
            source_ref="expired:test",
            title="Expired picking guidance",
            process_module="PICKING",
            content="Printed picking work can be replaced by controlled mobile tasks.",
            classification="INTERNAL",
            reusable_across_prospects=True,
            approval_state="APPROVED",
            expires_at=utcnow() - timedelta(days=1),
            created_by=me["id"],
        )
        db.add(expired)
        db.commit()
        snapshot = build_solution_snapshot(db, model, section_model)
        assert all(item["source_ref"] != "expired:test" for item in snapshot["approved_knowledge"])
