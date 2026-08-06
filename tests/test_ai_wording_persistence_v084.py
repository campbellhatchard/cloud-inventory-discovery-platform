from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "v0.8.9 AI Wording") -> tuple[str, dict]:
    h = headers(me)
    prospect = client.post(
        "/api/prospects",
        json={"name": name, "industry": "Distribution", "opportunity": "Durable AI wording"},
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


def enable_ai_for_test():
    from app.config import get_settings

    settings = get_settings()
    old = (
        settings.ai_enabled,
        settings.ai_confidential_content_enabled,
        settings.openai_data_control_mode,
        settings.openai_api_key,
    )
    settings.ai_enabled = True
    settings.ai_confidential_content_enabled = True
    settings.openai_data_control_mode = "zero_data_retention"
    settings.openai_api_key = "test-key"
    return settings, old


def restore_ai(settings, old) -> None:
    (
        settings.ai_enabled,
        settings.ai_confidential_content_enabled,
        settings.openai_data_control_mode,
        settings.openai_api_key,
    ) = old


def test_v084_version_migration_and_frontend_contract() -> None:
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    migration = (ROOT / "alembic" / "versions" / "i49f2a8d6b99_ai_wording_persistence.py").read_text(encoding="utf-8")
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.9"' in config
    assert 'down_revision = "h38e1f7c5a88"' in migration
    assert 'batch.add_column(sa.Column("source_fingerprint"' in migration
    assert 'batch.add_column(sa.Column("base_ai_text"' in migration
    assert 'batch.add_column(sa.Column("refinement_instruction"' in migration
    assert "/ai-wording/current" in app_js
    assert "force_regenerate:forceRegenerate" in app_js
    assert "Saved AI wording restored" in app_js
    assert "base_ai_wording" not in app_js  # base wording is assembled server-side only


def test_unchanged_wording_request_is_idempotent_and_restored(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, Report, ReportSection, utcnow

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "v084 Persisted Wording")
    section = next(item for item in payload["sections"] if item["process_module"] == "PICKING")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={
            "narrative": "Pickers use printed lists and supervisors communicate priority changes.",
            "expected_version": section["version"],
        },
        headers=h,
    )
    assert saved.status_code == 200, saved.text

    settings, old = enable_ai_for_test()
    try:
        first = client.post(
            f"/api/reports/{report_id}/ai",
            json={"section_id": section["id"], "purpose": "OBSERVATION_ENHANCEMENT", "evidence_ids": []},
            headers=h,
        )
        assert first.status_code == 202, first.text
        first_job_id = first.json()["ai_job_id"]

        duplicate = client.post(
            f"/api/reports/{report_id}/ai",
            json={"section_id": section["id"], "purpose": "OBSERVATION_ENHANCEMENT", "evidence_ids": []},
            headers=h,
        )
        assert duplicate.status_code == 202, duplicate.text
        assert duplicate.json()["ai_job_id"] == first_job_id
        assert duplicate.json()["reused"] is True

        with SessionLocal() as db:
            job = db.get(AiJob, first_job_id)
            assert job is not None
            report = db.get(Report, report_id)
            section_row = db.get(ReportSection, section["id"])
            assert report is not None and section_row is not None
            job.status = "COMPLETED"
            job.completed_at = utcnow() - timedelta(days=2)
            suggestion = AiSuggestion(
                ai_job_id=job.id,
                report_id=report_id,
                section_id=section["id"],
                purpose="OBSERVATION_ENHANCEMENT",
                content={
                    "enhanced_text": "Pickers work from printed lists, while supervisors communicate changes in priority.",
                    "suggested_text": "Pickers work from printed lists, while supervisors communicate changes in priority.",
                    "source_snapshot": job.context_snapshot,
                    "source_fingerprint": job.source_fingerprint,
                    "source_section_version": section_row.version,
                    "verification_status": "PASSED",
                    "accept_allowed": True,
                    "source_refs": [{"ref": "section:narrative", "label": "Section narrative"}],
                },
                source_refs=[{"ref": "section:narrative", "label": "Section narrative"}],
                confidence="HIGH",
                review_state="PENDING",
                source_fingerprint=job.source_fingerprint,
                created_at=utcnow() - timedelta(days=2),
            )
            db.add(suggestion)
            db.commit()
            suggestion_id = suggestion.id
            count_before = db.scalar(
                select(func.count(AiJob.id)).where(
                    AiJob.report_id == report_id,
                    AiJob.section_id == section["id"],
                    AiJob.purpose == "OBSERVATION_ENHANCEMENT",
                )
            )

        restored = client.get(
            f"/api/reports/{report_id}/sections/{section['id']}/ai-wording/current"
        )
        assert restored.status_code == 200, restored.text
        body = restored.json()
        assert body["is_current"] is True
        assert body["is_stale"] is False
        assert body["restored"] is True
        assert body["ai_job_id"] == first_job_id
        assert body["suggestion"]["id"] == suggestion_id
        assert "no new AI request" in body["message"].lower() or "restored" in body["message"].lower()

        requested_again = client.post(
            f"/api/reports/{report_id}/ai",
            json={"section_id": section["id"], "purpose": "OBSERVATION_ENHANCEMENT", "evidence_ids": []},
            headers=h,
        )
        assert requested_again.status_code == 202, requested_again.text
        assert requested_again.json()["ai_job_id"] == first_job_id
        assert requested_again.json()["reused"] is True

        with SessionLocal() as db:
            count_after = db.scalar(
                select(func.count(AiJob.id)).where(
                    AiJob.report_id == report_id,
                    AiJob.section_id == section["id"],
                    AiJob.purpose == "OBSERVATION_ENHANCEMENT",
                )
            )
        assert count_after == count_before == 1
    finally:
        restore_ai(settings, old)


def test_changed_sources_make_saved_wording_stale_and_block_refinement(admin_session) -> None:
    from app.ai_service import build_observation_snapshot
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, Report, ReportSection

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "v084 Stale Wording")
    section = next(item for item in payload["sections"] if item["process_module"] == "PACKING")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Orders are packed at shared benches.", "expected_version": section["version"]},
        headers=h,
    )
    assert saved.status_code == 200, saved.text

    with SessionLocal() as db:
        report = db.get(Report, report_id)
        section_row = db.get(ReportSection, section["id"])
        snapshot = build_observation_snapshot(db, report, section_row, [])
        job = AiJob(
            report_id=report_id,
            section_id=section["id"],
            purpose="OBSERVATION_ENHANCEMENT",
            instructions=None,
            model="test",
            policy_decision={"allowed": True},
            context_snapshot=snapshot,
            parent_suggestion_id=None,
            source_fingerprint=snapshot["source_fingerprint"],
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
                "enhanced_text": "Orders are packed at shared workbenches.",
                "source_snapshot": snapshot,
                "source_fingerprint": snapshot["source_fingerprint"],
                "source_section_version": section_row.version,
                "verification_status": "PASSED",
                "accept_allowed": True,
            },
            source_refs=[],
            confidence="HIGH",
            review_state="PENDING",
            source_fingerprint=snapshot["source_fingerprint"],
        )
        db.add(suggestion)
        db.commit()
        suggestion_id = suggestion.id

    current = client.get(f"/api/reports/{report_id}").json()
    latest_section = next(item for item in current["sections"] if item["id"] == section["id"])
    changed = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={
            "narrative": "Orders are packed at shared benches and weighed before labels are printed.",
            "expected_version": latest_section["version"],
        },
        headers=h,
    )
    assert changed.status_code == 200, changed.text

    restored = client.get(f"/api/reports/{report_id}/sections/{section['id']}/ai-wording/current")
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_stale"] is True
    assert restored.json()["suggestion"]["id"] == suggestion_id

    settings, old = enable_ai_for_test()
    try:
        refined = client.post(
            f"/api/reports/{report_id}/ai",
            json={
                "section_id": section["id"],
                "purpose": "OBSERVATION_ENHANCEMENT",
                "parent_suggestion_id": suggestion_id,
                "instructions": "Make this more concise.",
                "evidence_ids": [],
            },
            headers=h,
        )
        assert refined.status_code == 409
        assert "changed" in refined.json()["detail"]

        accepted = client.post(
            f"/api/reports/{report_id}/ai-suggestions/{suggestion_id}/review",
            json={"decision": "APPROVED"},
            headers=h,
        )
        assert accepted.status_code == 409
        assert "changed" in accepted.json()["detail"]
    finally:
        restore_ai(settings, old)


def test_refinement_payload_and_child_lineage_are_preserved(admin_session, monkeypatch) -> None:
    from app.ai_service import build_observation_snapshot, generate_observation_draft, process_ai_job
    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, Report, ReportSection

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "v084 Refinement Lineage")
    section = next(item for item in payload["sections"] if item["process_module"] == "RECEIVING")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={
            "narrative": "Receivers record deliveries on paper and later enter receipts into the host system.",
            "expected_version": section["version"],
        },
        headers=h,
    )
    assert saved.status_code == 200, saved.text

    captured: dict = {}

    def fake_call(settings, *, system, user_content, **kwargs):
        captured["system"] = system
        captured["payload"] = json.loads(user_content)
        return {
            "enhanced_text": "Receivers document deliveries on paper before entering receipts into the host system.",
            "source_refs": ["section:narrative"],
        }, {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}

    settings = get_settings().model_copy(update={"openai_api_key": "test-key"})
    with SessionLocal() as db:
        report = db.get(Report, report_id)
        section_row = db.get(ReportSection, section["id"])
        snapshot = build_observation_snapshot(db, report, section_row, [])
        parent_job = AiJob(
            report_id=report_id,
            section_id=section["id"],
            purpose="OBSERVATION_ENHANCEMENT",
            instructions=None,
            model="test",
            policy_decision={"allowed": True},
            context_snapshot=snapshot,
            source_fingerprint=snapshot["source_fingerprint"],
            status="COMPLETED",
            requested_by=me["id"],
        )
        db.add(parent_job)
        db.flush()
        parent = AiSuggestion(
            ai_job_id=parent_job.id,
            report_id=report_id,
            section_id=section["id"],
            purpose="OBSERVATION_ENHANCEMENT",
            content={
                "enhanced_text": "Receivers document deliveries manually and subsequently enter receipts in the host system.",
                "source_snapshot": snapshot,
                "source_fingerprint": snapshot["source_fingerprint"],
                "verification_status": "PASSED",
                "accept_allowed": True,
            },
            source_refs=[],
            confidence="HIGH",
            review_state="PENDING",
            source_fingerprint=snapshot["source_fingerprint"],
            base_ai_text="An earlier grandparent version that must not be refined.",
        )
        db.add(parent)
        db.commit()
        parent_id = parent.id

    monkeypatch.setattr("app.ai_service._call_json", fake_call)
    with SessionLocal() as db:
        parent = db.get(AiSuggestion, parent_id)
        report = db.get(Report, report_id)
        section_row = db.get(ReportSection, section["id"])
        snapshot = build_observation_snapshot(db, report, section_row, [])
        content, _ = generate_observation_draft(settings, snapshot, "Make it more concise.", parent)
        assert captured["payload"]["base_ai_wording"] == parent.content["enhanced_text"]
        assert captured["payload"]["refinement_request"] == "Make it more concise."
        assert "preserve wording" in captured["system"].lower()
        assert content["base_ai_text"] == parent.content["enhanced_text"]
        assert content["refinement_instruction"] == "Make it more concise."

    ai_settings, old = enable_ai_for_test()
    try:
        refined = client.post(
            f"/api/reports/{report_id}/ai",
            json={
                "section_id": section["id"],
                "purpose": "OBSERVATION_ENHANCEMENT",
                "parent_suggestion_id": parent_id,
                "instructions": "Make it more concise.",
                "evidence_ids": [],
            },
            headers=h,
        )
        assert refined.status_code == 202, refined.text
        child_job_id = refined.json()["ai_job_id"]

        def fake_draft(settings, snapshot, instructions, prior):
            return {
                "enhanced_text": "Receivers document deliveries on paper before entering receipts into the host system.",
                "suggested_text": "Receivers document deliveries on paper before entering receipts into the host system.",
                "base_ai_text": prior.content["enhanced_text"],
                "refinement_instruction": instructions,
                "parent_suggestion_id": prior.id,
                "source_snapshot": snapshot,
                "source_fingerprint": snapshot["source_fingerprint"],
                "source_section_version": snapshot["section"]["version"],
                "source_refs": [{"ref": "section:narrative", "label": "Section narrative"}],
                "verification_status": "VERIFYING",
                "accept_allowed": False,
                "workflow_stage": "DRAFT_READY",
            }, {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}

        def fake_finalize(settings, snapshot, draft):
            final = dict(draft)
            final.update({"verification_status": "PASSED", "accept_allowed": True, "workflow_stage": "COMPLETED"})
            return final, {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}

        monkeypatch.setattr("app.ai_service.generate_observation_draft", fake_draft)
        monkeypatch.setattr("app.ai_service.finalize_observation_draft", fake_finalize)
        worker_settings = get_settings().model_copy(update={
            "ai_enabled": True,
            "ai_confidential_content_enabled": True,
            "openai_data_control_mode": "zero_data_retention",
            "openai_api_key": "test-key",
        })
        with SessionLocal() as db:
            child = process_ai_job(db, child_job_id, worker_settings)
            child_id = child.id

        with SessionLocal() as db:
            parent = db.get(AiSuggestion, parent_id)
            child = db.get(AiSuggestion, child_id)
            assert child.parent_suggestion_id == parent_id
            assert child.base_ai_text == parent.content["enhanced_text"]
            assert child.refinement_instruction == "Make it more concise."
            assert child.source_fingerprint == parent.source_fingerprint
            assert parent.review_state == "SUPERSEDED"
            assert parent.superseded_by_suggestion_id == child.id
    finally:
        restore_ai(ai_settings, old)


def test_force_regenerate_creates_a_new_job_for_same_sources(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import AiJob

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "v084 Explicit Regenerate")
    section = next(item for item in payload["sections"] if item["process_module"] == "SHIPPING")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Shipping labels are printed at the end of packing.", "expected_version": section["version"]},
        headers=h,
    )
    assert saved.status_code == 200, saved.text

    settings, old = enable_ai_for_test()
    try:
        first = client.post(
            f"/api/reports/{report_id}/ai",
            json={"section_id": section["id"], "purpose": "OBSERVATION_ENHANCEMENT", "evidence_ids": []},
            headers=h,
        )
        forced = client.post(
            f"/api/reports/{report_id}/ai",
            json={
                "section_id": section["id"],
                "purpose": "OBSERVATION_ENHANCEMENT",
                "evidence_ids": [],
                "force_regenerate": True,
            },
            headers=h,
        )
        assert first.status_code == 202, first.text
        assert forced.status_code == 202, forced.text
        assert first.json()["ai_job_id"] != forced.json()["ai_job_id"]
        assert forced.json()["reused"] is False

        with SessionLocal() as db:
            jobs = list(
                db.scalars(
                    select(AiJob).where(
                        AiJob.report_id == report_id,
                        AiJob.section_id == section["id"],
                        AiJob.purpose == "OBSERVATION_ENHANCEMENT",
                    )
                ).all()
            )
            assert len(jobs) == 2
            assert jobs[0].source_fingerprint == jobs[1].source_fingerprint
    finally:
        restore_ai(settings, old)
