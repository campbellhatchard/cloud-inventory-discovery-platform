from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "Fast text regression") -> tuple[str, dict]:
    h = headers(me)
    prospect = client.post(
        "/api/prospects",
        json={"name": name, "industry": "Distribution", "opportunity": "Text AI regression"},
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


def test_v083_fast_text_history_is_retained_but_photo_lane_is_retired() -> None:
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    historical_migration = (ROOT / "alembic" / "versions" / "h38e1f7c5a88_ai_latency_photo_intelligence.py").read_text(encoding="utf-8")
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")
    ai_service = (ROOT / "app" / "ai_service.py").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.9"' in config
    assert 'down_revision = "g27d0e6b4f77"' in historical_migration
    assert '"fast-text": ("FAST_TEXT",)' in worker
    assert '"publication": ("PUBLICATION",)' in worker
    assert "PHOTO_ANALYSIS" not in worker
    assert "PHOTO_CONTEXT_REVISION" not in ai_service
    assert "input_image" not in ai_service


def test_job_queue_claims_only_requested_lane_and_lowest_priority_first() -> None:
    from app.database import SessionLocal
    from app.jobs import claim_next, enqueue
    from app.models import Job

    with SessionLocal() as db:
        later = enqueue(db, "test.v083", {"name": "later"}, queue_name="TEST_FAST_TEXT_V083", priority=50)
        other = enqueue(db, "test.v083", {"name": "other"}, queue_name="GENERAL_AI", priority=1)
        first = enqueue(db, "test.v083", {"name": "first"}, queue_name="TEST_FAST_TEXT_V083", priority=10)
        ids = [later.id, other.id, first.id]
        db.commit()

    with SessionLocal() as db:
        claimed = claim_next(db, "test-worker", queue_names=("TEST_FAST_TEXT_V083",))
        assert claimed is not None
        assert claimed.id == first.id
        assert claimed.queue_name == "TEST_FAST_TEXT_V083"

    with SessionLocal() as db:
        rows = list(db.scalars(select(Job).where(Job.id.in_(ids))).all())
        for row in rows:
            db.delete(row)
        db.commit()


def test_text_enhancement_remains_photo_free_and_uses_fast_text_lane(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import AiJob, Job

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "Fast Text v086")
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
            assert queue_job is not None
            assert queue_job.queue_name == "FAST_TEXT"
            assert queue_job.priority == 10

        rejected = client.post(
            f"/api/reports/{report_id}/ai",
            json={"section_id": section["id"], "purpose": "OBSERVATION_ENHANCEMENT", "evidence_ids": ["photo-id"]},
            headers=h,
        )
        assert rejected.status_code == 400
        assert "never sent to AI" in rejected.json()["detail"]
    finally:
        restore_ai(settings, old)
