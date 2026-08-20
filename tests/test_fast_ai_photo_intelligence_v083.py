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


def test_v090_preserves_historical_migration_and_separates_ai_lanes() -> None:
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    historical_migration = (ROOT / "alembic" / "versions" / "h38e1f7c5a88_ai_latency_photo_intelligence.py").read_text(encoding="utf-8")
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")
    photo_service = (ROOT / "app" / "photo_ai_service.py").read_text(encoding="utf-8")

    assert 'app_version: str = "0.9.0"' in config
    assert 'down_revision = "g27d0e6b4f77"' in historical_migration
    assert '"fast-text": ("FAST_TEXT",)' in worker
    assert '"ai-verification": ("AI_VERIFICATION",)' in worker
    assert '"photo-ai": ("PHOTO_AI",)' in worker
    assert '"publication": ("PUBLICATION",)' in worker
    assert "input_image" in photo_service
    assert "max_retries" in photo_service
    assert "openai_request_timeout_seconds" in config


def test_job_queue_claims_only_requested_lane_and_lowest_priority_first() -> None:
    from app.database import SessionLocal
    from app.jobs import claim_next, enqueue
    from app.models import Job

    with SessionLocal() as db:
        later = enqueue(db, "test.v090", {"name": "later"}, queue_name="TEST_FAST_TEXT_V090", priority=50)
        other = enqueue(db, "test.v090", {"name": "other"}, queue_name="GENERAL_AI", priority=1)
        first = enqueue(db, "test.v090", {"name": "first"}, queue_name="TEST_FAST_TEXT_V090", priority=10)
        ids = [later.id, other.id, first.id]
        db.commit()

    with SessionLocal() as db:
        claimed = claim_next(db, "test-worker", queue_names=("TEST_FAST_TEXT_V090",))
        assert claimed is not None
        assert claimed.id == first.id
        assert claimed.queue_name == "TEST_FAST_TEXT_V090"

    with SessionLocal() as db:
        rows = list(db.scalars(select(Job).where(Job.id.in_(ids))).all())
        for row in rows:
            db.delete(row)
        db.commit()


def test_fast_wording_is_photo_free_and_uses_dedicated_lane(admin_session) -> None:
    from app.database import SessionLocal
    from app.models import AiJob, Job

    client, me = admin_session
    h = headers(me)
    report_id, payload = create_report(client, me, "Fast Text v090")
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
            f"/api/reports/{report_id}/ai-fast-wording",
            json={"section_id": section["id"], "evidence_ids": []},
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
            assert queue_job.job_type == "ai.fast-wording"
            assert queue_job.queue_name == "FAST_TEXT"
            assert queue_job.priority == 5

        rejected = client.post(
            f"/api/reports/{report_id}/ai-fast-wording",
            json={"section_id": section["id"], "evidence_ids": ["photo-id"]},
            headers=h,
        )
        assert rejected.status_code == 400
        assert "Photo Intelligence is a separate workflow" in rejected.json()["detail"]
    finally:
        restore_ai(settings, old)


def test_v090_quick_entry_master_data_and_other_navigation_contract() -> None:
    script = (ROOT / "app" / "static" / "enhancements-v0.9.0.js").read_text(encoding="utf-8")
    upgrade = (ROOT / "app" / "v090_upgrade.py").read_text(encoding="utf-8")

    assert 'value: "MASTER_DATA", label: "Master Data"' in script
    assert 'stable_key === "master-data"' in script
    assert 'stable_key === "general-observations"' in script
    assert '.values(title="Other", display_order=255)' in upgrade
