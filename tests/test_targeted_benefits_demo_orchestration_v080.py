from __future__ import annotations

import io

from docx import Document
from sqlalchemy import select


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "v0.8.0 Prospect") -> tuple[str, dict]:
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


def create_solution_context(client, me, report_id: str, report: dict) -> tuple[dict, dict, dict]:
    request_headers = headers(me)
    section = next(item for item in report["sections"] if item["process_module"] == "PICKING")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={
            "narrative": "Picking priorities are communicated verbally and operators work from printed pick lists.",
            "expected_version": section["version"],
        },
        headers=request_headers,
    )
    assert saved.status_code == 200, saved.text
    capability_response = client.post(
        "/api/admin/capabilities",
        json={
            "capability_code": f"CAP-V080-{report_id[-6:]}",
            "name": "Controlled mobile picking",
            "domain": "PICKING",
            "controlled_description": "Presents configured picking work to authorized mobile users.",
            "typical_prerequisites": "Configured items, locations, users, and source-system order release.",
            "limitations": "Does not create source-system customer orders.",
            "status": "APPROVED",
            "source": "v0.8.0 test catalog",
        },
        headers=request_headers,
    )
    assert capability_response.status_code == 200, capability_response.text
    capability = next(
        item for item in client.get("/api/capabilities").json()
        if item["id"] == capability_response.json()["id"]
    )
    mapping = client.post(
        f"/api/reports/{report_id}/capability-mappings",
        json={
            "section_id": section["id"],
            "source_ref": "section:narrative",
            "capability_id": capability["id"],
            "rationale": "Controlled mobile work presentation can support the observed picking workflow.",
        },
        headers=request_headers,
    )
    assert mapping.status_code == 200, mapping.text
    approved = client.post(
        f"/api/reports/{report_id}/capability-mappings/{mapping.json()['id']}/review",
        json={"decision": "APPROVED"},
        headers=request_headers,
    )
    assert approved.status_code == 200, approved.text
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
    reloaded = client.get(f"/api/reports/{report_id}").json()
    section = next(item for item in reloaded["sections"] if item["id"] == section["id"])
    mapping_payload = next(item for item in reloaded["capability_mappings"] if item["id"] == mapping.json()["id"])
    return section, mapping_payload, capability


def test_manual_targeted_benefit_retains_mapping_source(admin_session):
    client, me = admin_session
    report_id, report = create_report(client, me, "Manual Benefit")
    section, mapping, _ = create_solution_context(client, me, report_id, report)
    response = client.post(
        f"/api/reports/{report_id}/benefits",
        json={
            "section_id": section["id"],
            "capability_mapping_id": mapping["id"],
            "statement": "Reduce reliance on verbal coordination when prioritizing picking work.",
            "category": "WORKFORCE_PRODUCTIVITY",
            "measure_type": "QUALITATIVE",
            "confidence": "HIGH",
        },
        headers=headers(me),
    )
    assert response.status_code == 200, response.text
    payload = client.get(f"/api/reports/{report_id}").json()
    benefit = next(item for item in payload["benefits"] if item["id"] == response.json()["id"])
    assert benefit["section_id"] == section["id"]
    assert benefit["source_ref"] == f"mapping:{mapping['id']}"
    assert benefit["source_type"] == "CAPABILITY_MAPPING"
    assert benefit["category"] == "WORKFORCE_PRODUCTIVITY"
    assert benefit["approval_state"] == "PENDING"


def test_quantitative_benefit_requires_metric_formula_and_assumptions(admin_session):
    client, me = admin_session
    report_id, report = create_report(client, me, "Quantitative Benefit")
    section, mapping, _ = create_solution_context(client, me, report_id, report)
    rejected = client.post(
        f"/api/reports/{report_id}/benefits",
        json={
            "section_id": section["id"],
            "capability_mapping_id": mapping["id"],
            "statement": "Reduce picking time by 20%.",
            "measure_type": "QUANTITATIVE",
            "formula": "",
            "assumptions": "",
        },
        headers=headers(me),
    )
    assert rejected.status_code == 400
    metric = client.post(
        f"/api/reports/{report_id}/metrics",
        json={
            "section_id": section["id"],
            "name": "Average picking minutes per order",
            "value_numeric": 18,
            "unit": "minutes",
            "source": "Observed baseline",
            "confidence": "HIGH",
        },
        headers=headers(me),
    )
    assert metric.status_code == 200, metric.text
    accepted = client.post(
        f"/api/reports/{report_id}/benefits",
        json={
            "section_id": section["id"],
            "source_ref": f"metric:{metric.json()['id']}",
            "statement": "Measure change in average picking minutes per order after implementation.",
            "measure_type": "QUANTITATIVE",
            "formula": "Post-implementation average minus baseline average",
            "assumptions": "Comparable order mix and measurement period.",
            "confidence": "MEDIUM",
        },
        headers=headers(me),
    )
    assert accepted.status_code == 200, accepted.text


def test_targeted_benefit_snapshot_contains_solution_mapping_and_metrics(admin_session):
    from app.ai_service import build_targeted_benefits_snapshot
    from app.database import SessionLocal
    from app.models import Report, ReportSection

    client, me = admin_session
    report_id, report = create_report(client, me, "Benefit Snapshot")
    section, mapping, _ = create_solution_context(client, me, report_id, report)
    metric = client.post(
        f"/api/reports/{report_id}/metrics",
        json={"section_id": section["id"], "name": "Urgent orders per day", "value_numeric": 12, "unit": "orders"},
        headers=headers(me),
    )
    assert metric.status_code == 200
    with SessionLocal() as db:
        snapshot = build_targeted_benefits_snapshot(
            db,
            db.get(Report, report_id),
            db.get(ReportSection, section["id"]),
        )
    assert snapshot["solution"]["text"].startswith("Cloud Inventory can present")
    assert any(item["id"] == mapping["id"] for item in snapshot["approved_mappings"])
    assert any(item["id"] == metric.json()["id"] for item in snapshot["metrics"])
    assert any(item["ref"].startswith("finding:") and item["finding_type"] == "OBSERVATION" for item in snapshot["operational_sources"])


def test_targeted_benefit_suggestion_accepts_selected_items_as_pending(admin_session):
    from app.ai_service import build_targeted_benefits_snapshot
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, Report, ReportSection

    client, me = admin_session
    report_id, report = create_report(client, me, "AI Benefit Acceptance")
    section, mapping, _ = create_solution_context(client, me, report_id, report)
    with SessionLocal() as db:
        snapshot = build_targeted_benefits_snapshot(
            db,
            db.get(Report, report_id),
            db.get(ReportSection, section["id"]),
        )
        job = AiJob(
            report_id=report_id,
            section_id=section["id"],
            purpose="TARGETED_BENEFITS",
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
            section_id=section["id"],
            purpose="TARGETED_BENEFITS",
            content={
                "benefits": [
                    {
                        "statement": "Reduce reliance on verbal task prioritization.",
                        "category": "WORKFORCE_PRODUCTIVITY",
                        "measure_type": "QUALITATIVE",
                        "formula": None,
                        "assumptions": None,
                        "confidence": "HIGH",
                        "source_refs": [f"mapping:{mapping['id']}", "section:narrative"],
                    },
                    {
                        "statement": "Improve management visibility of outstanding picking work.",
                        "category": "MANAGEMENT_VISIBILITY",
                        "measure_type": "QUALITATIVE",
                        "formula": None,
                        "assumptions": None,
                        "confidence": "MEDIUM",
                        "source_refs": [f"mapping:{mapping['id']}"],
                    },
                ],
                "verification_status": "PASSED",
                "accept_allowed": True,
                "source_section_version": section["version"],
                "source_report_revision": snapshot["report"]["revision"],
                "source_snapshot": snapshot,
            },
            source_refs=[],
            confidence="HIGH",
            review_state="PENDING",
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id
    response = client.post(
        f"/api/reports/{report_id}/ai-suggestions/{suggestion_id}/review",
        json={"decision": "APPROVED", "selected_item_indexes": [1]},
        headers=headers(me),
    )
    assert response.status_code == 200, response.text
    assert response.json()["applied"]["benefits"] == 1
    payload = client.get(f"/api/reports/{report_id}").json()
    accepted = [item for item in payload["benefits"] if item["ai_suggestion_id"] == suggestion_id]
    assert len(accepted) == 1
    assert accepted[0]["statement"].startswith("Improve management visibility")
    assert accepted[0]["approval_state"] == "PENDING"


def test_demo_settings_and_section_priorities_are_versioned(admin_session):
    client, me = admin_session
    report_id, report = create_report(client, me, "Demo Inputs")
    section = next(item for item in report["sections"] if item["process_module"] == "PICKING")
    settings = client.put(
        f"/api/reports/{report_id}/demo-settings",
        json={"audience": "Operations leadership and IT", "duration_minutes": 45, "additional_priorities": "Start with receiving."},
        headers=headers(me),
    )
    assert settings.status_code == 200, settings.text
    priority = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/demo-priority",
        json={"priority": "MUST_SHOW", "user_notes": "Show urgent work prioritization.", "constraints": "Do not create ERP orders.", "estimated_minutes": 12},
        headers=headers(me),
    )
    assert priority.status_code == 200, priority.text
    payload = client.get(f"/api/reports/{report_id}").json()
    assert payload["demo_settings"]["audience"] == "Operations leadership and IT"
    item = next(row for row in payload["demo_section_priorities"] if row["section_id"] == section["id"])
    assert item["priority"] == "MUST_SHOW"
    stale = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/demo-priority",
        json={"priority": "OPTIONAL", "expected_version": 99},
        headers=headers(me),
    )
    assert stale.status_code == 409


def test_demo_plan_acceptance_creates_current_version(admin_session):
    from app.ai_service import build_demo_plan_snapshot
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, DemoPlanVersion, Report

    client, me = admin_session
    report_id, report = create_report(client, me, "Demo Acceptance")
    section, mapping, _ = create_solution_context(client, me, report_id, report)
    client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/demo-priority",
        json={"priority": "MUST_SHOW", "user_notes": "Show configured picking priorities.", "estimated_minutes": 10},
        headers=headers(me),
    )
    refreshed = client.get(f"/api/reports/{report_id}").json()
    with SessionLocal() as db:
        snapshot = build_demo_plan_snapshot(db, db.get(Report, report_id))
        job = AiJob(
            report_id=report_id,
            section_id=None,
            purpose="DEMO_PLAN",
            model="test-model",
            policy_decision={"allowed": True},
            context_snapshot=snapshot,
            status="COMPLETED",
            requested_by=me["id"],
        )
        db.add(job)
        db.flush()
        plan = {
            "title": "Customer Picking Demonstration",
            "audience": "Operations leadership",
            "duration_minutes": 45,
            "objectives": ["Demonstrate controlled mobile picking work."],
            "flow": [{
                "sequence": 1,
                "section_id": section["id"],
                "operational_area": section["title"],
                "priority": "MUST_SHOW",
                "functionality": "Configured mobile picking tasks",
                "scenario": "Release and complete an urgent picking task.",
                "customer_context": "Priority changes are currently communicated verbally.",
                "value_statement": "Provide supervisors visibility of outstanding picking work.",
                "sample_data": "Two picking orders with different priorities.",
                "user_role": "Picker and supervisor",
                "steps": ["Open the mobile task list.", "Complete the urgent task."],
                "expected_result": "The urgent task is presented according to configured rules.",
                "talking_points": ["ERP retains order ownership."],
                "questions": ["How are urgent orders identified today?"],
                "capability_mapping_ids": [mapping["id"]],
                "source_refs": [f"mapping:{mapping['id']}", "section:narrative"],
                "estimated_minutes": 10,
            }],
            "risks_to_avoid": ["Do not imply ERP order creation."],
            "open_questions": [],
            "preparation_notes": ["Prepare urgent and standard sample orders."],
        }
        suggestion = AiSuggestion(
            ai_job_id=job.id,
            report_id=report_id,
            section_id=None,
            purpose="DEMO_PLAN",
            content={
                "demo_plan": plan,
                "verification_status": "PASSED",
                "accept_allowed": True,
                "source_report_revision": refreshed["report"]["revision"],
                "source_snapshot": snapshot,
                "source_refs": [{"ref": f"mapping:{mapping['id']}", "label": mapping["capability_name"]}],
            },
            source_refs=[],
            confidence="HIGH",
            review_state="PENDING",
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id
    response = client.post(
        f"/api/reports/{report_id}/ai-suggestions/{suggestion_id}/review",
        json={"decision": "APPROVED"},
        headers=headers(me),
    )
    assert response.status_code == 200, response.text
    assert response.json()["applied"]["demo_plan"] is True
    payload = client.get(f"/api/reports/{report_id}").json()
    assert payload["demo_plan"]["content"]["title"] == "Customer Picking Demonstration"
    with SessionLocal() as db:
        version = db.scalar(select(DemoPlanVersion).where(DemoPlanVersion.report_id == report_id, DemoPlanVersion.is_current.is_(True)))
        assert version is not None
        assert version.ai_suggestion_id == suggestion_id


def test_demo_brief_uses_accepted_demo_plan(admin_session):
    from app.config import get_settings
    from app.database import SessionLocal
    from app.documents import generate_docx
    from app.models import DemoPlanVersion

    client, me = admin_session
    report_id, report = create_report(client, me, "Demo Document")
    section, mapping, _ = create_solution_context(client, me, report_id, report)
    with SessionLocal() as db:
        db.add(DemoPlanVersion(
            report_id=report_id,
            version=1,
            content={
                "title": "Structured Demo Plan",
                "audience": "Warehouse leadership",
                "duration_minutes": 30,
                "objectives": ["Show controlled task execution."],
                "flow": [{
                    "sequence": 1,
                    "section_id": section["id"],
                    "operational_area": "Picking",
                    "priority": "MUST_SHOW",
                    "functionality": "Mobile picking tasks",
                    "scenario": "Complete an urgent pick.",
                    "customer_context": "Urgent work is communicated verbally.",
                    "value_statement": "Support visibility of outstanding work.",
                    "sample_data": "Urgent order 1001",
                    "user_role": "Picker",
                    "steps": ["Open task list", "Complete task"],
                    "expected_result": "Task completes through configured workflow.",
                    "talking_points": ["ERP retains order ownership."],
                    "questions": ["How are priorities assigned?"],
                    "capability_mapping_ids": [mapping["id"]],
                    "source_refs": [f"mapping:{mapping['id']}"],
                    "estimated_minutes": 10,
                }],
                "risks_to_avoid": ["Do not imply automatic ERP order creation."],
                "open_questions": [],
                "preparation_notes": ["Prepare two sample orders."],
            },
            source_type="AI_ACCEPTED",
            source_refs=[],
            is_current=True,
            created_by=me["id"],
        ))
        db.commit()
        data = generate_docx(db, report_id, get_settings(), publication_type="DEMO_BRIEF", is_final=False)
    document = Document(io.BytesIO(data))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Demo Objectives" in text
    assert "Structured Demo Plan" not in text  # title remains metadata; structured sections drive the document
    assert "Mobile picking tasks" in text
    assert "Claims and Risks to Avoid" in text
    assert "Do not imply automatic ERP order creation" in text


def test_frontend_contains_targeted_benefit_and_demo_orchestration_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="targeted-benefits"' in app_js
    assert 'data-action="generate-targeted-benefits"' in app_js
    assert 'id="section-demo-priority-form"' in app_js
    assert 'id="demo-settings-form"' in app_js
    assert 'data-action="generate-demo-plan"' in app_js
    assert "Add selected benefits for review" in app_js
    assert "Claims and risks to avoid" in app_js
