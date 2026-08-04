from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "v0.8.3 AI Prospect") -> tuple[str, dict]:
    h = headers(me)
    prospect = client.post(
        "/api/prospects",
        json={"name": name, "industry": "Distribution", "opportunity": "AI latency and photo intelligence"},
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


def jpeg_bytes(size: tuple[int, int] = (480, 320)) -> bytes:
    image = Image.new("RGB", size, "white")
    output = io.BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


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


def test_v083_version_migration_and_worker_lane_contract() -> None:
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    migration = (ROOT / "alembic" / "versions" / "h38e1f7c5a88_ai_latency_photo_intelligence.py").read_text(encoding="utf-8")
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")
    jobs = (ROOT / "app" / "jobs.py").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.5"' in config
    assert 'down_revision = "g27d0e6b4f77"' in migration
    assert 'batch.add_column(sa.Column("queue_name"' in migration
    assert 'batch.add_column(sa.Column("priority"' in migration
    assert '"fast-text": ("FAST_TEXT",)' in worker
    assert '"photo-analysis": ("PHOTO_ANALYSIS",)' in worker
    assert '"publication": ("PUBLICATION",)' in worker
    assert "stmt.order_by(Job.priority.asc(), Job.created_at.asc())" in jobs


def test_job_queue_claims_only_requested_lane_and_lowest_priority_first() -> None:
    from app.database import SessionLocal
    from app.jobs import claim_next, enqueue
    from app.models import Job

    with SessionLocal() as db:
        fast_later = enqueue(db, "test.v083", {"name": "fast-later"}, queue_name="TEST_FAST_TEXT_V083", priority=50)
        photo = enqueue(db, "test.v083", {"name": "photo"}, queue_name="PHOTO_ANALYSIS", priority=1)
        fast_first = enqueue(db, "test.v083", {"name": "fast-first"}, queue_name="TEST_FAST_TEXT_V083", priority=10)
        ids = [fast_later.id, photo.id, fast_first.id]
        db.commit()

    with SessionLocal() as db:
        claimed = claim_next(db, "test-worker", queue_names=("TEST_FAST_TEXT_V083",))
        assert claimed is not None
        assert claimed.id == fast_first.id
        assert claimed.queue_name == "TEST_FAST_TEXT_V083"

    with SessionLocal() as db:
        rows = list(db.scalars(select(Job).where(Job.id.in_(ids))).all())
        for row in rows:
            db.delete(row)
        db.commit()


def test_text_enhancement_is_photo_free_and_uses_fast_text_lane(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import AiJob, Job

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "v083 Fast Text")
    section = next(item for item in payload["sections"] if item["process_module"] == "PICKING")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Pickers receive printed pick lists and supervisors advise priority changes.", "expected_version": section["version"]},
        headers=h,
    )
    assert saved.status_code == 200, saved.text

    settings, old = enable_ai_for_test()
    try:
        requested = client.post(
            f"/api/reports/{report_id}/ai",
            json={"section_id": section["id"], "purpose": "OBSERVATION_ENHANCEMENT", "evidence_ids": []},
            headers=h,
        )
        assert requested.status_code == 202, requested.text
        ai_job_id = requested.json()["ai_job_id"]
        with SessionLocal() as db:
            ai_job = db.get(AiJob, ai_job_id)
            queue_job = db.scalar(select(Job).where(Job.payload["ai_job_id"].as_string() == ai_job_id))
            assert ai_job is not None
            assert ai_job.context_snapshot["selected_evidence_ids"] == []
            assert all(item.get("type") != "PHOTO" for item in ai_job.context_snapshot["sources"])
            assert queue_job is not None
            assert queue_job.queue_name == "FAST_TEXT"
            assert queue_job.priority == 10

        rejected = client.post(
            f"/api/reports/{report_id}/ai",
            json={"section_id": section["id"], "purpose": "OBSERVATION_ENHANCEMENT", "evidence_ids": ["photo-id"]},
            headers=h,
        )
        assert rejected.status_code == 400
        assert "Photographs are analyzed independently" in rejected.json()["detail"]
    finally:
        restore_ai(settings, old)


def test_fast_text_draft_is_committed_before_verification_finishes(admin_session, monkeypatch) -> None:
    from app.ai_service import process_ai_job
    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion

    client, me = admin_session
    report_id, payload = create_report(client, me, "v083 Draft Ready")
    section = next(item for item in payload["sections"] if item["process_module"] == "PACKING")

    def fake_draft(settings, snapshot, instructions, prior):
        return {
            "original_text": "boxes weighed",
            "enhanced_text": "Packed orders are weighed before shipment.",
            "suggested_text": "Packed orders are weighed before shipment.",
            "verification_status": "VERIFYING",
            "accept_allowed": False,
            "source_refs": [{"ref": "section:narrative", "label": "Section narrative"}],
            "source_section_version": snapshot["section"]["version"],
            "workflow_stage": "DRAFT_READY",
        }, {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}

    observed = {}

    def fake_finalize(settings, snapshot, draft):
        with SessionLocal() as observer:
            current_job = observer.get(AiJob, observed["job_id"])
            current_suggestion = observer.scalar(select(AiSuggestion).where(AiSuggestion.ai_job_id == observed["job_id"]))
            observed["status_during_verify"] = current_job.status
            observed["draft_visible"] = current_suggestion.content["workflow_stage"]
            observed["accept_during_verify"] = current_suggestion.content["accept_allowed"]
        final = dict(draft)
        final.update({"verification_status": "PASSED", "accept_allowed": True, "workflow_stage": "COMPLETED"})
        return final, {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}

    monkeypatch.setattr("app.ai_service.generate_observation_draft", fake_draft)
    monkeypatch.setattr("app.ai_service.finalize_observation_draft", fake_finalize)
    settings = get_settings().model_copy(update={
        "ai_enabled": True,
        "ai_confidential_content_enabled": True,
        "openai_data_control_mode": "zero_data_retention",
        "openai_api_key": "test-key",
    })

    with SessionLocal() as db:
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
            requested_by=me["id"],
        )
        db.add(job)
        db.commit()
        observed["job_id"] = job.id
        suggestion = process_ai_job(db, job.id, settings)
        assert suggestion.content["verification_status"] == "PASSED"

    assert observed["status_during_verify"] == "VERIFYING"
    assert observed["draft_visible"] == "DRAFT_READY"
    assert observed["accept_during_verify"] is False


def test_photo_analysis_queues_independent_lane_and_returns_cached_result(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import EvidenceAiObservation, FileObject, Job

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "v083 Photo Queue")
    section = next(item for item in payload["sections"] if item["process_module"] == "RECEIVING")
    uploaded = client.post(
        f"/api/reports/{report_id}/evidence",
        data={"section_id": section["id"], "caption": "Do not use this caption as visual context", "placement": "INLINE", "classification": "CONFIDENTIAL"},
        files={"file": ("receiving.jpg", jpeg_bytes(), "image/jpeg")},
        headers=h,
    )
    assert uploaded.status_code == 200, uploaded.text
    evidence_id = uploaded.json()["id"]

    settings, old = enable_ai_for_test()
    try:
        requested = client.post(
            f"/api/reports/{report_id}/sections/{section['id']}/photo-analysis",
            json={"evidence_ids": [evidence_id]},
            headers=h,
        )
        assert requested.status_code == 202, requested.text
        row = requested.json()["jobs"][0]
        assert row["status"] == "QUEUED"
        with SessionLocal() as db:
            queue_job = db.scalar(select(Job).where(Job.payload["ai_job_id"].as_string() == row["ai_job_id"]))
            assert queue_job is not None
            assert queue_job.queue_name == "PHOTO_ANALYSIS"
            assert queue_job.priority == 50
            web_file = db.scalar(
                select(FileObject)
                .where(FileObject.evidence_id == evidence_id, FileObject.variant == "WEB")
            )
            assert web_file is not None
            db.add(EvidenceAiObservation(
                evidence_id=evidence_id,
                report_id=report_id,
                section_id=section["id"],
                model="test-model",
                source_file_sha256=web_file.sha256,
                content={
                    "visible_observations": ["Palletized loads are visible."],
                    "operational_interpretations": [],
                    "uncertainties": ["Workflow state is not visible."],
                    "detail_used": "low",
                    "detail_escalation_reason": None,
                },
            ))
            db.commit()

        cached = client.post(
            f"/api/reports/{report_id}/sections/{section['id']}/photo-analysis",
            json={"evidence_ids": [evidence_id]},
            headers=h,
        )
        assert cached.status_code == 202, cached.text
        assert cached.json()["jobs"][0]["status"] == "CACHED"
        assert cached.json()["jobs"][0]["ai_job_id"] is None
    finally:
        restore_ai(settings, old)


def test_photo_context_snapshot_uses_cached_analysis_not_raw_images(admin_session) -> None:
    from app.ai_service import build_photo_context_snapshot
    from app.database import SessionLocal
    from app.models import EvidenceAiObservation, EvidenceItem, FileObject, Report, ReportSection

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "v083 Photo Context")
    section = next(item for item in payload["sections"] if item["process_module"] == "PUTAWAY")
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": "Material is staged before putaway.", "expected_version": section["version"]},
        headers=h,
    )
    assert saved.status_code == 200, saved.text
    uploaded = client.post(
        f"/api/reports/{report_id}/evidence",
        data={"section_id": section["id"], "caption": "Staging area", "placement": "INLINE", "classification": "CONFIDENTIAL"},
        files={"file": ("putaway.jpg", jpeg_bytes(), "image/jpeg")},
        headers=h,
    )
    evidence_id = uploaded.json()["id"]

    with SessionLocal() as db:
        web_file = db.scalar(select(FileObject).where(FileObject.evidence_id == evidence_id, FileObject.variant == "WEB"))
        evidence = db.get(EvidenceItem, evidence_id)
        db.add(EvidenceAiObservation(
            evidence_id=evidence_id,
            report_id=report_id,
            section_id=section["id"],
            model="test-model",
            source_file_sha256=web_file.sha256,
            content={
                "visible_observations": ["Several palletized loads are positioned on the floor."],
                "operational_interpretations": ["The area may be used for temporary staging."],
                "uncertainties": ["The photograph does not establish the next process step."],
                "detail_used": "low",
                "detail_escalation_reason": None,
            },
        ))
        db.commit()
        report = db.get(Report, report_id)
        report_section = db.get(ReportSection, section["id"])
        snapshot = build_photo_context_snapshot(db, report, report_section, [evidence.id])

    assert snapshot["section"]["original_narrative"] == "Material is staged before putaway."
    assert snapshot["selected_evidence_ids"] == [evidence_id]
    assert snapshot["photo_observations"][0]["analysis"]["visible_observations"]
    serialized = str(snapshot)
    assert "image_url" not in serialized
    assert "base64" not in serialized.lower()
    assert all(item.get("type") != "PHOTO" for item in snapshot["sources"])


def test_photo_context_acceptance_preserves_prior_narrative_and_source_type(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import AiJob, AiSuggestion, SectionContentVersion

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "v083 Photo Apply")
    section = next(item for item in payload["sections"] if item["process_module"] == "SHIPPING")
    original = "Orders are staged before carrier pickup."
    saved = client.patch(
        f"/api/reports/{report_id}/sections/{section['id']}",
        json={"narrative": original, "expected_version": section["version"]},
        headers=h,
    ).json()

    revised = "Orders are staged before carrier pickup; photographed evidence shows palletized loads positioned in a floor staging area."
    with SessionLocal() as db:
        job = AiJob(
            report_id=report_id,
            section_id=section["id"],
            purpose="PHOTO_CONTEXT_REVISION",
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
            purpose="PHOTO_CONTEXT_REVISION",
            content={
                "original_text": original,
                "suggested_text": revised,
                "enhanced_text": revised,
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
        json={"decision": "APPROVED", "note": "Apply photo-supported revision"},
        headers=h,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["applied"]["narrative"] is True

    with SessionLocal() as db:
        versions = list(
            db.scalars(
                select(SectionContentVersion)
                .where(SectionContentVersion.section_id == section["id"])
                .order_by(SectionContentVersion.version)
            ).all()
        )
        assert versions[-2].text == original
        assert versions[-1].text == revised
        assert versions[-1].source_type == "AI_PHOTO_CONTEXT"
        assert versions[-1].is_current is True


def test_frontend_has_no_ai_timeout_and_separates_photo_workflow() -> None:
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    ai_service = (ROOT / "app" / "ai_service.py").read_text(encoding="utf-8")

    assert "AI enhancement timed out" not in app_js
    assert "for (let attempt = 0; attempt < 90" not in app_js[app_js.index("async function pollAiEnhancement"):app_js.index("async function requestAiEnhancement")]
    assert "Preparing a fast text-only wording draft" in app_js
    assert 'id="photo-analysis"' in app_js
    assert 'data-action="analyze-selected-photos"' in app_js
    assert 'data-action="compare-photo-context"' in app_js
    assert "The original image files are not sent again during this stage." in app_js
    assert '"detail": detail' in ai_service
    assert 'content, usage = analyze("low")' in ai_service
    assert "You have no written process context" in ai_service
    assert ".photo-analysis-grid" in styles
