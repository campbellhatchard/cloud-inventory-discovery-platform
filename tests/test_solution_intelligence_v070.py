from __future__ import annotations

import io

from docx import Document
from sqlalchemy import select


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "Solution Intelligence Prospect") -> tuple[str, dict]:
    h = headers(me)
    prospect = client.post("/api/prospects", json={"name": name, "industry": "Distribution"}, headers=h).json()
    site = client.post(f"/api/prospects/{prospect['id']}/sites", json={"name": "Main DC"}, headers=h).json()
    engagement = client.post(
        f"/api/prospects/{prospect['id']}/engagements",
        json={"name": "Site walk", "site_id": site["id"], "survey_date": "2026-08-03"},
        headers=h,
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
        headers=h,
    ).json()
    return report["id"], client.get(f"/api/reports/{report['id']}").json()


def approved_capability(client, me, code: str, domain: str = "Picking") -> dict:
    response = client.post(
        "/api/admin/capabilities",
        json={
            "capability_code": code,
            "name": f"{domain} controlled capability {code}",
            "domain": domain,
            "controlled_description": "Provides controlled mobile task execution using configured operational rules.",
            "typical_prerequisites": "Configured items, locations, users, and integration ownership.",
            "limitations": "Behavior depends on approved configuration and source-system integration.",
            "status": "APPROVED",
            "source": "v0.7.0 test catalog",
        },
        headers=headers(me),
    )
    assert response.status_code == 200, response.text
    return next(item for item in client.get("/api/capabilities").json() if item["id"] == response.json()["id"])


def test_general_notes_are_mapping_observations(admin_session):
    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "General Notes Mapping")
    section = next(item for item in payload["sections"] if item["process_module"] == "PICKING")
    capability = approved_capability(client, me, "CAP-V070-GENERAL")

    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Pickers receive priority changes verbally from a supervisor.", "expected_version": section["version"]},
        headers=h,
    )
    assert saved.status_code == 200, saved.text

    mapping = client.post(
        f"/api/reports/{report_id}/capability-mappings",
        json={
            "section_id": section["id"],
            "source_ref": "section:narrative",
            "capability_id": capability["id"],
            "rationale": "Controlled task visibility can support the observed prioritization workflow.",
        },
        headers=h,
    )
    assert mapping.status_code == 200, mapping.text

    reloaded = client.get(f"/api/reports/{report_id}").json()
    item = next(row for row in reloaded["capability_mappings"] if row["id"] == mapping.json()["id"])
    assert item["section_id"] == section["id"]
    assert item["finding_id"] is None
    assert item["source_ref"] == "section:narrative"
    assert item["source_type"] == "GENERAL_OBSERVATION"
    assert item["source_label"].startswith("Observation")
    assert "priority changes verbally" in item["source_statement"]


def test_solution_snapshot_uses_general_notes_findings_and_approved_knowledge(admin_session):
    from app.ai_service import build_solution_snapshot
    from app.database import SessionLocal
    from app.models import Report, ReportSection

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "Solution Snapshot")
    section = next(item for item in payload["sections"] if item["process_module"] == "PICKING")
    capability = approved_capability(client, me, "CAP-V070-SNAPSHOT")

    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Operators use printed pick lists and confirm completion at a shared workstation.", "expected_version": section["version"]},
        headers=h,
    )
    assert saved.status_code == 200

    refreshed = client.get(f"/api/reports/{report_id}").json()
    section = next(item for item in refreshed["sections"] if item["id"] == section["id"])
    prompt = next(item for item in refreshed["prompts_by_module"]["PICKING"] if item["answer_type"] != "PHOTO")
    response = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/responses",
        json={"prompt_id": prompt["id"], "narrative": "Urgent work is communicated verbally during the shift.", "client_mutation_id": "v070-snapshot-response"},
        headers=h,
    )
    assert response.status_code == 200, response.text

    finding = client.post(
        f"/api/reports/{report_id}/findings",
        json={"section_id": section["id"], "finding_type": "PAIN_POINT", "statement": "Priority work can be difficult to distinguish from standard work.", "confidence": "HIGH"},
        headers=h,
    )
    assert finding.status_code == 200

    knowledge = client.post(
        "/api/admin/knowledge",
        json={
            "source_type": "APPROVED_REPORT_LANGUAGE",
            "source_ref": "test:v070:snapshot",
            "title": "Directed picking wording",
            "process_module": "PICKING",
            "content": "Approved explanation: configured task queues can present work to mobile users according to defined operational rules.",
            "capability_id": capability["id"],
            "classification": "INTERNAL",
            "reusable_across_prospects": True,
        },
        headers=h,
    )
    assert knowledge.status_code == 200
    reviewed = client.post(
        f"/api/admin/knowledge/{knowledge.json()['id']}/review",
        json={"decision": "APPROVED", "reusable_across_prospects": True},
        headers=h,
    )
    assert reviewed.status_code == 200, reviewed.text

    with SessionLocal() as db:
        report = db.get(Report, report_id)
        db_section = db.get(ReportSection, section["id"])
        snapshot = build_solution_snapshot(db, report, db_section)

    narrative = next(item for item in snapshot["operational_sources"] if item["ref"] == "section:narrative")
    assert narrative["source_type"] == "GENERAL_OBSERVATION"
    assert narrative["finding_type"] == "OBSERVATION"
    guided = next(item for item in snapshot["operational_sources"] if item["ref"].startswith("response:"))
    assert guided["source_type"] == "GENERAL_OBSERVATION"
    explicit = next(item for item in snapshot["operational_sources"] if item["ref"] == f"finding:{finding.json()['id']}")
    assert explicit["finding_type"] == "PAIN_POINT"
    assert any(item["id"] == capability["id"] for item in snapshot["approved_capabilities"])
    assert any(item["id"] == knowledge.json()["id"] for item in snapshot["approved_knowledge"])


def test_solution_acceptance_creates_version_and_general_observation_mapping(admin_session):
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, Capability, SectionContentVersion

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "Solution Acceptance")
    section = next(item for item in payload["sections"] if item["process_module"] == "PICKING")
    capability = approved_capability(client, me, "CAP-V070-ACCEPT")

    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Pickers work from printed lists and receive reprioritization verbally.", "expected_version": section["version"]},
        headers=h,
    ).json()

    with SessionLocal() as db:
        cap = db.get(Capability, capability["id"])
        job = AiJob(
            report_id=report_id,
            section_id=section["id"],
            purpose="SOLUTION_APPROACH",
            instructions=None,
            model="test-model",
            policy_decision={"allowed": True, "reason": "test", "mode": "zero_data_retention"},
            context_snapshot={},
            status="COMPLETED",
            requested_by=me["id"],
        )
        db.add(job)
        db.flush()
        suggestion = AiSuggestion(
            ai_job_id=job.id,
            report_id=report_id,
            section_id=section["id"],
            purpose="SOLUTION_APPROACH",
            content={
                "solution_text": "Cloud Inventory can present configured picking work through controlled mobile task execution, reducing reliance on printed work lists while retaining source-system ownership of the order.",
                "suggested_text": "Cloud Inventory can present configured picking work through controlled mobile task execution, reducing reliance on printed work lists while retaining source-system ownership of the order.",
                "capability_mappings": [{
                    "capability_id": cap.id,
                    "source_ref": "section:narrative",
                    "rationale": "The approved mobile task capability supports controlled presentation of picking work.",
                    "prerequisites": cap.typical_prerequisites,
                    "knowledge_refs": [],
                }],
                "verification_status": "PASSED",
                "accept_allowed": True,
                "source_section_version": saved["version"],
                "source_snapshot": {
                    "approved_capabilities": [{"id": cap.id, "version": cap.version}],
                    "approved_knowledge": [],
                },
                "source_refs": [{"ref": "section:narrative", "label": "Observation — Current operations narrative"}],
            },
            source_refs=[{"ref": "section:narrative", "label": "Observation — Current operations narrative"}],
            confidence="HIGH",
            review_state="PENDING",
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id

    accepted = client.post(
        f"/api/reports/{report_id}/ai-suggestions/{suggestion_id}/review",
        json={"decision": "APPROVED", "note": "Approved solution wording"},
        headers=h,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["applied"]["solution"] is True
    assert accepted.json()["applied"]["mappings"] == 1

    reloaded = client.get(f"/api/reports/{report_id}").json()
    target = next(item for item in reloaded["sections"] if item["id"] == section["id"])
    assert target["cloud_inventory_approach"]["text"].startswith("Cloud Inventory can present configured picking work")
    mapping = next(item for item in reloaded["capability_mappings"] if item["ai_suggestion_id"] == suggestion_id)
    assert mapping["finding_id"] is None
    assert mapping["source_type"] == "GENERAL_OBSERVATION"
    assert mapping["approval_state"] == "APPROVED"

    with SessionLocal() as db:
        versions = list(db.scalars(select(SectionContentVersion).where(
            SectionContentVersion.section_id == section["id"],
            SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH",
        )).all())
        assert len(versions) == 1
        assert versions[0].is_current is True
        assert versions[0].ai_suggestion_id == suggestion_id


def test_solution_suggestion_is_stale_after_operational_edit(admin_session):
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, Capability

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "Solution Stale")
    section = next(item for item in payload["sections"] if item["process_module"] == "RECEIVING")
    capability = approved_capability(client, me, "CAP-V070-STALE", domain="Receiving")
    first = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Receipts are entered at a desktop workstation.", "expected_version": section["version"]},
        headers=h,
    ).json()

    with SessionLocal() as db:
        cap = db.get(Capability, capability["id"])
        job = AiJob(report_id=report_id, section_id=section["id"], purpose="SOLUTION_APPROACH", model="test", policy_decision={"allowed": True}, context_snapshot={}, status="COMPLETED", requested_by=me["id"])
        db.add(job)
        db.flush()
        suggestion = AiSuggestion(
            ai_job_id=job.id, report_id=report_id, section_id=section["id"], purpose="SOLUTION_APPROACH",
            content={
                "solution_text": "Controlled receipt processing can support the observed operation.", "suggested_text": "Controlled receipt processing can support the observed operation.",
                "capability_mappings": [{"capability_id": cap.id, "source_ref": "section:narrative", "rationale": "Supports receipt execution."}],
                "verification_status": "PASSED", "accept_allowed": True, "source_section_version": first["version"],
                "source_snapshot": {"approved_capabilities": [{"id": cap.id, "version": cap.version}], "approved_knowledge": []},
            }, source_refs=[], confidence="HIGH", review_state="PENDING",
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id

    changed = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Receipts are entered at a desktop workstation after paperwork review.", "expected_version": first["version"]},
        headers=h,
    )
    assert changed.status_code == 200
    accepted = client.post(f"/api/reports/{report_id}/ai-suggestions/{suggestion_id}/review", json={"decision": "APPROVED"}, headers=h)
    assert accepted.status_code == 409
    assert "changed after" in accepted.json()["detail"].lower()


def test_historical_knowledge_import_is_pending_until_approved(admin_session):
    from app.ai_service import build_solution_snapshot
    from app.database import SessionLocal
    from app.models import Report, ReportSection

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "Knowledge Import")
    section = next(item for item in payload["sections"] if item["process_module"] == "PACKING")
    capability = approved_capability(client, me, "CAP-V070-KNOWLEDGE", domain="Packing")
    client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Orders are packed at fixed benches before shipment.", "expected_version": section["version"]},
        headers=h,
    )

    imported = client.post(
        "/api/admin/knowledge/import",
        data={"title": "Historical packing explanation", "process_module": "PACKING", "capability_id": capability["id"], "prospect_id": ""},
        files={"file": ("packing-notes.txt", b"Approved historical wording describing controlled packing unit creation and shipment preparation.", "text/plain")},
        headers=h,
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 1
    entry_id = imported.json()["entry_ids"][0]

    with SessionLocal() as db:
        snapshot = build_solution_snapshot(db, db.get(Report, report_id), db.get(ReportSection, section["id"]))
        assert all(item["id"] != entry_id for item in snapshot["approved_knowledge"])

    reviewed = client.post(
        f"/api/admin/knowledge/{entry_id}/review",
        json={"decision": "APPROVED", "reusable_across_prospects": True, "note": "Reviewed and approved as shared internal wording."},
        headers=h,
    )
    assert reviewed.status_code == 200, reviewed.text
    with SessionLocal() as db:
        snapshot = build_solution_snapshot(db, db.get(Report, report_id), db.get(ReportSection, section["id"]))
        assert any(item["id"] == entry_id for item in snapshot["approved_knowledge"])


def test_report_document_includes_cloud_inventory_approach(admin_session):
    from app.database import SessionLocal
    from app.models import Capability, CapabilityMapping, SectionContentVersion

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "Solution Document")
    section = next(item for item in payload["sections"] if item["process_module"] == "SHIPPING")
    capability = approved_capability(client, me, "CAP-V070-DOC", domain="Shipping")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Shipment confirmation is completed after loading.", "expected_version": section["version"]},
        headers=h,
    )
    assert saved.status_code == 200

    with SessionLocal() as db:
        cap = db.get(Capability, capability["id"])
        db.add(SectionContentVersion(
            report_id=report_id, section_id=section["id"], content_type="CLOUD_INVENTORY_APPROACH", version=1,
            text="Cloud Inventory can support controlled shipment confirmation using approved outbound execution capabilities.",
            source_type="AI_ACCEPTED", source_refs=[], is_current=True, created_by=me["id"],
        ))
        db.add(CapabilityMapping(
            report_id=report_id, section_id=section["id"], finding_id=None, source_ref="section:narrative", source_type="GENERAL_OBSERVATION",
            source_label="Observation — Current operations narrative", source_statement="Shipment confirmation is completed after loading.",
            capability_id=cap.id, rationale="Supports controlled shipment confirmation.", approval_state="APPROVED", approved_by=me["id"], created_by=me["id"],
        ))
        db.commit()

    response = client.get(f"/api/reports/{report_id}/draft.docx")
    assert response.status_code == 200, response.text
    doc = Document(io.BytesIO(response.content))
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Cloud Inventory Approach" in text
    assert "Cloud Inventory can support controlled shipment confirmation" in text
    assert "Mapped Cloud Inventory Functionality" in text
    assert "Mapped from Observation" in text


def test_frontend_solution_intelligence_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (root / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    assert 'data-action="generate-solution-approach"' in app_js
    assert 'id="ai-solution-modal"' in app_js
    assert "automatically treated as <strong>Observations</strong>" in app_js
    assert "purpose:'SOLUTION_APPROACH'" in app_js
    assert 'data-action="accept-solution-approach"' in app_js
    assert 'data-action="import-knowledge"' in app_js
    assert 'id="knowledge-import-form"' in app_js
    assert ".general-observation-summary" in styles
    assert ".solution-approach-text" in styles
