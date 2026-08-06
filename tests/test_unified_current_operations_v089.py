from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.current_operations import append_narrative_entry, parse_current_operations_narrative
from app.database import SessionLocal
from app.models import Capability, CapabilityMapping, Finding

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "Unified Current Operations") -> tuple[str, dict]:
    h = headers(me)
    prospect = client.post(
        "/api/prospects",
        json={"name": name, "industry": "Distribution", "opportunity": "Unified narrative"},
        headers=h,
    )
    assert prospect.status_code == 200, prospect.text
    prospect_id = prospect.json()["id"]
    site = client.post(
        f"/api/prospects/{prospect_id}/sites",
        json={"name": "Operations", "address": "Kansas", "timezone": "America/Chicago"},
        headers=h,
    )
    engagement = client.post(
        f"/api/prospects/{prospect_id}/engagements",
        json={"name": "Survey", "site_id": site.json()["id"], "survey_date": "2026-08-06"},
        headers=h,
    )
    template = client.get("/api/report-templates").json()[0]
    report = client.post(
        f"/api/prospects/{prospect_id}/reports",
        json={
            "title": name,
            "engagement_id": engagement.json()["id"],
            "site_id": site.json()["id"],
            "report_template_id": template["id"],
            "report_kind": "CAPTURE",
        },
        headers=h,
    )
    assert report.status_code == 200, report.text
    report_id = report.json()["id"]
    return report_id, client.get(f"/api/reports/{report_id}").json()


def test_narrative_format_and_parser_preserve_selected_types() -> None:
    text = append_narrative_entry("", finding_type="OBSERVATION", statement="Operators receive at two doors.")
    text = append_narrative_entry(
        text,
        finding_type="PAIN_POINT",
        statement="Receipts are keyed after unloading.",
        impact="Inventory visibility is delayed.",
    )
    text = append_narrative_entry(text, finding_type="RISK", statement="Damaged stock can enter staging.")

    assert text.startswith("Observation:\nOperators receive at two doors.")
    assert "Pain Point:\nReceipts are keyed after unloading.\nImpact: Inventory visibility is delayed." in text
    assert "Risk:\nDamaged stock can enter staging." in text

    parsed = parse_current_operations_narrative(text)
    assert [entry.finding_type for entry in parsed] == ["OBSERVATION", "PAIN_POINT", "RISK"]
    assert parsed[1].impact == "Inventory visibility is delayed."


def test_quick_entry_appends_to_single_current_operations_narrative(admin_session) -> None:
    client, me = admin_session
    report_id, report = create_report(client, me)
    receiving = next(section for section in report["sections"] if section["process_module"] == "RECEIVING")

    response = client.post(
        f"/api/reports/{report_id}/quick-capture",
        json={
            "section_id": receiving["id"],
            "note": "Receipts are staged before system confirmation.",
            "finding_type": "PAIN_POINT",
            "impact": "On-hand visibility is delayed.",
            "client_mutation_id": "v089-quick-1",
        },
        headers=headers(me),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "Pain Point:\nReceipts are staged before system confirmation." in body["narrative"]
    assert "Impact: On-hand visibility is delayed." in body["narrative"]

    refreshed = client.get(f"/api/reports/{report_id}").json()
    receiving = next(section for section in refreshed["sections"] if section["id"] == receiving["id"])
    assert receiving["narrative"] == body["narrative"]
    current = [item for item in refreshed["findings"] if item["section_id"] == receiving["id"]]
    assert len(current) == 1
    assert current[0]["finding_type"] == "PAIN_POINT"
    assert current[0]["source_type"] == "NARRATIVE_DERIVED"

    duplicate = client.post(
        f"/api/reports/{report_id}/quick-capture",
        json={
            "section_id": receiving["id"],
            "note": "Receipts are staged before system confirmation.",
            "finding_type": "PAIN_POINT",
            "client_mutation_id": "v089-quick-1",
        },
        headers=headers(me),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["deduplicated"] is True
    assert client.get(f"/api/reports/{report_id}").json()["findings"] == refreshed["findings"]


def test_manual_narrative_edit_resynchronizes_classification_and_stales_old_mapping(admin_session) -> None:
    client, me = admin_session
    report_id, report = create_report(client, me, "Narrative Resync")
    picking = next(section for section in report["sections"] if section["process_module"] == "PICKING")
    captured = client.post(
        f"/api/reports/{report_id}/quick-capture",
        json={
            "section_id": picking["id"],
            "note": "Priority picks are communicated verbally.",
            "finding_type": "PAIN_POINT",
            "client_mutation_id": "v089-resync-1",
        },
        headers=headers(me),
    )
    assert captured.status_code == 200
    old_finding_id = captured.json()["id"]

    with SessionLocal() as db:
        capability = Capability(
            capability_code="CAP-V089-RESYNC",
            name="Directed Picking Test",
            domain="PICKING",
            controlled_description="Test capability",
            status="APPROVED",
        )
        db.add(capability)
        db.flush()
        db.add(
            CapabilityMapping(
                report_id=report_id,
                section_id=picking["id"],
                finding_id=old_finding_id,
                source_ref=f"finding:{old_finding_id}",
                source_type="FINDING",
                source_label="Pain Point",
                source_statement="Priority picks are communicated verbally.",
                capability_id=capability.id,
                rationale="Test mapping",
                approval_state="APPROVED",
                approved_by=me["id"],
                created_by=me["id"],
            )
        )
        db.commit()

    new_text = "Pain Point:\nPriority picks are identified on a printed hot list."
    updated = client.patch(
        f"/api/reports/{report_id}/sections/{picking['id']}",
        json={"narrative": new_text, "expected_version": captured.json()["version"]},
        headers=headers(me),
    )
    assert updated.status_code == 200, updated.text
    current = updated.json()["findings"]
    assert len(current) == 1
    assert current[0]["statement"] == "Priority picks are identified on a printed hot list."
    assert current[0]["id"] != old_finding_id

    with SessionLocal() as db:
        old = db.get(Finding, old_finding_id)
        assert old and old.status == "SUPERSEDED"
        mapping = db.scalar(select(CapabilityMapping).where(CapabilityMapping.finding_id == old_finding_id))
        assert mapping is not None
        assert mapping.approval_state == "STALE"


def test_unified_current_operations_frontend_and_ai_contract() -> None:
    app_js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    ai_service = (ROOT / "app/ai_service.py").read_text(encoding="utf-8")
    documents = (ROOT / "app/documents.py").read_text(encoding="utf-8")

    assert "single editable record of current operations" in app_js
    assert 'id="findings"' not in app_js
    assert 'data-action="new-finding"' not in app_js
    assert 'id="finding-form"' not in app_js
    assert "Current-State Findings" not in app_js
    assert "Current-State Findings" not in documents
    assert "Preserve those classifications and do not flatten, remove, rename, or invent classification headings" in ai_service


def test_v089_migration_contract() -> None:
    migration = (ROOT / "alembic/versions/n94k7f3i1g54_unified_current_operations_narrative.py").read_text(encoding="utf-8")
    models = (ROOT / "app/models.py").read_text(encoding="utf-8")
    config = (ROOT / "app/config.py").read_text(encoding="utf-8")

    assert 'revision = "n94k7f3i1g54"' in migration
    assert 'down_revision = "m83j6e2h0f43"' in migration
    assert "NARRATIVE_DERIVED" in migration
    assert "report_sections SET narrative" in migration
    assert 'source_type: Mapped[str] = mapped_column(String(30), default="LEGACY")' in models
    assert 'app_version: str = "0.8.9"' in config
