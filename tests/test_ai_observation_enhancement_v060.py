from __future__ import annotations

from sqlalchemy import select


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "AI Enhancement Prospect") -> tuple[str, dict]:
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


def test_observation_request_snapshots_section_sources(admin_session):
    from app.config import get_settings

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "AI Snapshot")
    section = next(item for item in payload["sections"] if item["process_module"] == "PICKING")

    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Pickers receive work from a printed list.", "expected_version": section["version"]},
        headers=h,
    )
    assert saved.status_code == 200, saved.text

    settings = get_settings()
    old = (settings.ai_enabled, settings.ai_confidential_content_enabled, settings.openai_data_control_mode, settings.openai_api_key)
    settings.ai_enabled = True
    settings.ai_confidential_content_enabled = True
    settings.openai_data_control_mode = "zero_data_retention"
    settings.openai_api_key = "test-key"
    try:
        requested = client.post(
            f"/api/reports/{report_id}/ai",
            json={"section_id": section["id"], "purpose": "OBSERVATION_ENHANCEMENT", "evidence_ids": []},
            headers=h,
        )
        assert requested.status_code == 202, requested.text
        from app.database import SessionLocal
        from app.models import AiJob
        with SessionLocal() as db:
            job = db.get(AiJob, requested.json()["ai_job_id"])
            assert job is not None
            assert job.context_snapshot["section"]["id"] == section["id"]
            assert job.context_snapshot["section"]["original_narrative"] == "Pickers receive work from a printed list."
            assert any(item["ref"] == "section:narrative" for item in job.context_snapshot["sources"])
    finally:
        settings.ai_enabled, settings.ai_confidential_content_enabled, settings.openai_data_control_mode, settings.openai_api_key = old


def test_observation_ai_acceptance_replaces_narrative_and_preserves_original(admin_session):
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, ReportSection, SectionContentVersion

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "AI Acceptance")
    section = next(item for item in payload["sections"] if item["process_module"] == "RECEIVING")
    original = "receiving note short pallets checked then entered desktop"
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": original, "expected_version": section["version"]},
        headers=h,
    ).json()

    with SessionLocal() as db:
        job = AiJob(
            report_id=report_id,
            section_id=section["id"],
            purpose="OBSERVATION_ENHANCEMENT",
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
            purpose="OBSERVATION_ENHANCEMENT",
            content={
                "original_text": original,
                "enhanced_text": "Receiving personnel check incoming pallets before recording the receipt at a desktop workstation.",
                "suggested_text": "Receiving personnel check incoming pallets before recording the receipt at a desktop workstation.",
                "verification_status": "PASSED",
                "accept_allowed": True,
                "source_section_version": saved["version"],
                "source_refs": [{"ref": "section:narrative", "label": "Section narrative"}],
            },
            source_refs=[{"ref": "section:narrative", "label": "Section narrative"}],
            confidence="HIGH",
            review_state="PENDING",
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id

    accepted = client.post(
        f"/api/reports/{report_id}/ai-suggestions/{suggestion_id}/review",
        json={"decision": "APPROVED", "note": "Use customer-facing wording"},
        headers=h,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["applied"]["narrative"] is True

    reloaded = client.get(f"/api/reports/{report_id}").json()
    receiving = next(item for item in reloaded["sections"] if item["id"] == section["id"])
    assert receiving["narrative"].startswith("Receiving personnel check incoming pallets")

    with SessionLocal() as db:
        versions = list(
            db.scalars(
                select(SectionContentVersion)
                .where(SectionContentVersion.section_id == section["id"])
                .order_by(SectionContentVersion.version)
            ).all()
        )
        assert len(versions) == 2
        assert versions[0].text == original
        assert versions[0].source_type == "USER"
        assert versions[1].source_type == "AI_ACCEPTED"
        assert versions[1].is_current is True
        assert db.get(ReportSection, section["id"]).narrative == versions[1].text


def test_blocked_ai_text_cannot_be_accepted(admin_session):
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "AI Blocked")
    section = next(item for item in payload["sections"] if item["process_module"] == "PUTAWAY")

    with SessionLocal() as db:
        job = AiJob(
            report_id=report_id,
            section_id=section["id"],
            purpose="OBSERVATION_ENHANCEMENT",
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
            purpose="OBSERVATION_ENHANCEMENT",
            content={
                "original_text": "",
                "enhanced_text": "Unsupported claim.",
                "verification_status": "BLOCKED",
                "accept_allowed": False,
                "unsupported_claims": [{"text": "Unsupported claim.", "reason": "Not in source."}],
            },
            source_refs=[],
            confidence="MEDIUM",
            review_state="PENDING",
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id

    accepted = client.post(
        f"/api/reports/{report_id}/ai-suggestions/{suggestion_id}/review",
        json={"decision": "APPROVED"},
        headers=h,
    )
    assert accepted.status_code == 409
    assert "unsupported claims" in accepted.json()["detail"].lower()


def test_process_observation_job_uses_specialized_pipeline(admin_session, monkeypatch):
    from app.ai_service import process_ai_job
    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import AiJob, User

    client, me = admin_session
    report_id, payload = create_report(client, me, "AI Process")
    section = next(item for item in payload["sections"] if item["process_module"] == "PACKING")

    def fake_draft(settings, snapshot, instructions, prior):
        assert snapshot["section"]["id"] == section["id"]
        assert prior is None
        return {
            "original_text": "boxes weighed",
            "enhanced_text": "Packed orders are weighed before shipment.",
            "suggested_text": "Packed orders are weighed before shipment.",
            "verification_status": "VERIFYING",
            "accept_allowed": False,
            "source_refs": [{"ref": "section:narrative", "label": "Section narrative"}],
            "source_section_version": section["version"],
            "workflow_stage": "DRAFT_READY",
        }, {"input_tokens": 60, "output_tokens": 15, "total_tokens": 75}

    def fake_finalize(settings, snapshot, draft):
        result = dict(draft)
        result.update({"verification_status": "PASSED", "accept_allowed": True, "workflow_stage": "COMPLETED"})
        return result, {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}

    monkeypatch.setattr("app.ai_service.generate_observation_draft", fake_draft)
    monkeypatch.setattr("app.ai_service.finalize_observation_draft", fake_finalize)
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
            purpose="OBSERVATION_ENHANCEMENT",
            instructions=None,
            model=settings.openai_model,
            policy_decision={"allowed": True, "reason": "test", "mode": "zero_data_retention"},
            context_snapshot={
                "report": {"id": report_id},
                "section": {"id": section["id"], "version": section["version"], "original_narrative": "boxes weighed"},
                "selected_evidence_ids": [],
                "sources": [{"ref": "section:narrative", "type": "SECTION_NARRATIVE", "label": "Section narrative", "text": "boxes weighed"}],
            },
            status="QUEUED",
            requested_by=actor.id,
        )
        db.add(job)
        db.commit()
        suggestion = process_ai_job(db, job.id, settings)
        assert suggestion.purpose == "OBSERVATION_ENHANCEMENT"
        assert suggestion.confidence == "HIGH"
        assert suggestion.content["verification_status"] == "PASSED"


def test_frontend_ai_comparison_and_tts_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (root / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    assert 'data-action="ai-enhance-observations"' in app_js
    assert 'id="ai-enhancement-modal"' in app_js
    assert "Original entered content" in app_js
    assert "AI-enhanced wording" in app_js
    assert "speechSynthesis" in app_js
    assert 'data-action="refine-ai-enhancement"' in app_js
    assert 'data-action="accept-ai-enhancement"' in app_js
    assert 'id="photo-analysis"' in app_js
    assert 'data-action="analyze-selected-photos"' in app_js
    assert 'data-action="compare-photo-context"' in app_js
    assert 'id="ai-photo-picker"' not in app_js
    assert ".ai-comparison-grid" in styles


def test_observation_request_rejects_evidence_from_another_section(admin_session):
    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import EvidenceItem

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "AI Evidence Scope")
    picking = next(item for item in payload["sections"] if item["process_module"] == "PICKING")
    packing = next(item for item in payload["sections"] if item["process_module"] == "PACKING")
    prospect_id = payload["report"]["prospect_id"]

    with SessionLocal() as db:
        evidence = EvidenceItem(
            prospect_id=prospect_id,
            report_id=report_id,
            section_id=packing["id"],
            evidence_type="PHOTO",
            caption="Packing workstation",
            status="READY",
            created_by=me["id"],
        )
        db.add(evidence)
        db.commit()
        evidence_id = evidence.id

    settings = get_settings()
    old = (settings.ai_enabled, settings.ai_confidential_content_enabled, settings.openai_data_control_mode, settings.openai_api_key)
    settings.ai_enabled = True
    settings.ai_confidential_content_enabled = True
    settings.openai_data_control_mode = "zero_data_retention"
    settings.openai_api_key = "test-key"
    try:
        requested = client.post(
            f"/api/reports/{report_id}/ai",
            json={
                "section_id": picking["id"],
                "purpose": "OBSERVATION_ENHANCEMENT",
                "evidence_ids": [evidence_id],
            },
            headers=h,
        )
        assert requested.status_code == 400
        assert "Photographs are analyzed independently" in requested.json()["detail"]
    finally:
        settings.ai_enabled, settings.ai_confidential_content_enabled, settings.openai_data_control_mode, settings.openai_api_key = old


def test_stale_observation_suggestion_cannot_overwrite_newer_section_edit(admin_session):
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "AI Stale")
    section = next(item for item in payload["sections"] if item["process_module"] == "SHIPPING")

    first = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Orders are staged before carrier pickup.", "expected_version": section["version"]},
        headers=h,
    ).json()

    with SessionLocal() as db:
        job = AiJob(
            report_id=report_id,
            section_id=section["id"],
            purpose="OBSERVATION_ENHANCEMENT",
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
            purpose="OBSERVATION_ENHANCEMENT",
            content={
                "original_text": "Orders are staged before carrier pickup.",
                "enhanced_text": "Completed orders are staged prior to carrier pickup.",
                "verification_status": "PASSED",
                "accept_allowed": True,
                "source_section_version": first["version"],
                "source_refs": [{"ref": "section:narrative", "label": "Section narrative"}],
            },
            source_refs=[{"ref": "section:narrative", "label": "Section narrative"}],
            confidence="HIGH",
            review_state="PENDING",
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id

    newer = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Orders are staged by carrier lane before pickup.", "expected_version": first["version"]},
        headers=h,
    )
    assert newer.status_code == 200, newer.text

    accepted = client.post(
        f"/api/reports/{report_id}/ai-suggestions/{suggestion_id}/review",
        json={"decision": "APPROVED"},
        headers=h,
    )
    assert accepted.status_code == 409
    assert "section changed" in accepted.json()["detail"].lower()

    reloaded = client.get(f"/api/reports/{report_id}").json()
    shipping = next(item for item in reloaded["sections"] if item["id"] == section["id"])
    assert shipping["narrative"] == "Orders are staged by carrier lane before pickup."
