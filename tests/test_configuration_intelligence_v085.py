from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "v0.8.5 Configuration Intelligence") -> tuple[str, dict]:
    h = headers(me)
    prospect = client.post(
        "/api/prospects",
        json={"name": name, "industry": "Distribution", "opportunity": "Configuration intelligence"},
        headers=h,
    )
    assert prospect.status_code == 200, prospect.text
    prospect_id = prospect.json()["id"]
    site = client.post(
        f"/api/prospects/{prospect_id}/sites",
        json={"name": "Main Warehouse", "timezone": "America/Chicago"},
        headers=h,
    )
    assert site.status_code == 200, site.text
    engagement = client.post(
        f"/api/prospects/{prospect_id}/engagements",
        json={"name": "Site walk", "site_id": site.json()["id"], "survey_date": "2026-08-04"},
        headers=h,
    )
    assert engagement.status_code == 200, engagement.text
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
    report_id = report.json()["id"]
    return report_id, client.get(f"/api/reports/{report_id}").json()


def test_v085_seed_contains_controlled_configuration_knowledge() -> None:
    seed = json.loads((ROOT / "assets" / "configuration-knowledge-seed.json").read_text(encoding="utf-8"))
    assert seed["_meta"]["effective_configuration_source_version"] == "2.7"
    assert seed["_meta"]["corroborating_source_version"] == "2.6"
    assert seed["_meta"]["record_count"] == 126
    assert len(seed["records"]) == 126
    assert all(item["structured_data"]["never_use_as_discovery_prompt"] is True for item in seed["records"])

    locations = {item["structured_data"]["source_question_id"]: item for item in seed["records"] if item["structured_data"]["source_question_id"].startswith("gs-loc-")}
    assert len(locations) == 10
    assert locations["gs-loc-002"]["capability_code"] == "CAP-LOC-001"
    assert "Receiving" in locations["gs-loc-002"]["content"]
    assert "Fixed Picking" in locations["gs-loc-002"]["content"]
    assert "capacity and dimensions are checked" in locations["gs-loc-007"]["content"]
    assert "Hazmat" in locations["gs-loc-008"]["content"]
    assert "Cold storage" in locations["gs-loc-008"]["content"]

    crossdock = next(item for item in seed["records"] if item["structured_data"]["source_question_id"] == "gs-ns-003")
    assert crossdock["capability_code"] is None
    assert crossdock["structured_data"]["claim_strength"] == "SCOPE_SIGNAL_ONLY"
    assert "does not establish standard Cloud Inventory support" in crossdock["content"]


def test_high_level_capabilities_remain_succinct(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import Capability

    with SessionLocal() as db:
        for code in ["CAP-ORG-001", "CAP-LOC-001", "CAP-BCS-001", "CAP-INV-001", "CAP-REQ-001"]:
            capability = db.scalar(select(Capability).where(Capability.capability_code == code))
            assert capability is not None
            assert capability.status == "APPROVED"
            assert len(capability.controlled_description) <= 150
            assert "nsC7" not in capability.controlled_description
            assert "PS action" not in capability.controlled_description


def test_seeded_configuration_is_repository_knowledge_not_discovery_prompts(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import KnowledgeEntry, PromptDefinition

    with SessionLocal() as db:
        config_count = db.scalar(select(func.count(KnowledgeEntry.id)).where(KnowledgeEntry.knowledge_kind == "PRODUCT_CONFIGURATION"))
        source_prompt_count = db.scalar(select(func.count(PromptDefinition.id)).where(PromptDefinition.stable_key.like("gs-%")))
        assert config_count == 126
        assert source_prompt_count == 0
        loc = db.scalar(select(KnowledgeEntry).where(KnowledgeEntry.source_ref == "configuration:guided-setup:gs-loc-007"))
        assert loc is not None
        assert loc.approval_state == "APPROVED"
        assert loc.reusable_across_prospects is True
        assert loc.structured_data["never_use_as_discovery_prompt"] is True


def test_location_observation_retrieves_location_configuration_knowledge(admin_session) -> None:
    from app.ai_service import build_solution_snapshot
    from app.database import SessionLocal
    from app.models import Report, ReportSection

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "Location Intelligence")
    section = next(item for item in payload["sections"] if item["process_module"] == "PUTAWAY")
    update = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={
            "narrative": (
                "The site has no formal location numbering or location identification and no warehouse zones. "
                "Receiving, fixed picking, bulk rack storage and packing areas are not system-defined. "
                "Operators choose storage based on available space and use pallet jacks, forklifts and high-rise reach trucks. "
                "Some rack positions have different physical capacity."
            ),
            "expected_version": section["version"],
        },
        headers=h,
    )
    assert update.status_code == 200, update.text

    with SessionLocal() as db:
        report = db.get(Report, report_id)
        sec = db.get(ReportSection, section["id"])
        snapshot = build_solution_snapshot(db, report, sec)
        cap = next(item for item in snapshot["approved_capabilities"] if item["code"] == "CAP-LOC-001")
        assert cap["name"] == "Location and Zone Management"
        refs = {item["source_ref"] for item in snapshot["approved_knowledge"] if item["knowledge_kind"] == "PRODUCT_CONFIGURATION"}
        assert "configuration:guided-setup:gs-loc-002" in refs
        assert "configuration:guided-setup:gs-loc-003" in refs or "configuration:guided-setup:gs-loc-004" in refs
        assert "configuration:guided-setup:gs-loc-007" in refs
        assert "configuration:guided-setup:gs-loc-008" in refs
        assert all(item.get("structured_data", {}).get("knowledge_role") != "PLATFORM_SETUP" for item in snapshot["approved_knowledge"])


def test_configuration_import_never_creates_discovery_questions(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import KnowledgeEntry, PromptDefinition

    client, me = admin_session
    h = headers(me)
    template = {
        "_meta": {"version": "2.8", "description": "Test controlled configuration source"},
        "sections": [
            {
                "id": "section-locations",
                "title": "Locations & Zones",
                "questions": [
                    {
                        "id": "gs-loc-test-280",
                        "text": "Should locations support a test configuration option?",
                        "guidance": "System object: nsC7TestConfiguration. Platform help: Test behavior is configurable.",
                        "type": "choice",
                        "options": ["Option A", "Option B"],
                        "branches": [],
                        "source": "System object: nsC7TestConfiguration (Guided Setup connector)",
                    }
                ],
            }
        ],
    }
    raw = json.dumps(template).encode("utf-8")

    with SessionLocal() as db:
        before_prompts = db.scalar(select(func.count(PromptDefinition.id)))
    result = client.post(
        "/api/admin/knowledge/import-configuration",
        files={"file": ("guided-setup-v2.8.json", raw, "application/json")},
        headers=h,
    )
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 1
    assert result.json()["discovery_prompts_created"] == 0

    with SessionLocal() as db:
        after_prompts = db.scalar(select(func.count(PromptDefinition.id)))
        entry = db.scalar(select(KnowledgeEntry).where(KnowledgeEntry.source_ref == "configuration:guided-setup:gs-loc-test-280"))
        assert after_prompts == before_prompts
        assert entry is not None
        assert entry.knowledge_kind == "PRODUCT_CONFIGURATION"
        assert entry.approval_state == "PENDING"
        assert entry.structured_data["never_use_as_discovery_prompt"] is True


def test_zip_loader_selects_highest_guided_setup_version() -> None:
    from app.configuration_intelligence import load_configuration_template

    low = {"_meta": {"version": "2.6"}, "sections": []}
    high = {"_meta": {"version": "2.8"}, "sections": [{"id": "x", "title": "Locations & Zones", "questions": []}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("old.json", json.dumps(low))
        zf.writestr("current.json", json.dumps(high))
        zf.writestr("ignore.html", "<html></html>")
    loaded = load_configuration_template(buf.getvalue(), "bundle.zip")
    assert loaded["_meta"]["version"] == "2.8"


def test_solution_prompt_explicitly_blocks_configuration_question_leakage() -> None:
    source = (ROOT / "app" / "ai_service.py").read_text(encoding="utf-8")
    assert "Do not turn configuration source material into discovery questions" in source
    assert "Do not expose raw source-question wording, nsC7 object/field identifiers" in source
    assert "Treat approved capability descriptions as deliberately high-level and concise" in source
