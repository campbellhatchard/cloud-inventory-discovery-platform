from __future__ import annotations

from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def _create_report(client, me, name: str = "v0.8.11 Page Simplification") -> tuple[str, dict]:
    headers = _headers(me)
    prospect = client.post("/api/prospects", json={"name": name, "industry": "Distribution"}, headers=headers).json()
    site = client.post(
        f"/api/prospects/{prospect['id']}/sites",
        json={"name": "Main DC"},
        headers=headers,
    ).json()
    engagement = client.post(
        f"/api/prospects/{prospect['id']}/engagements",
        json={"name": "Site walk", "site_id": site["id"], "survey_date": "2026-08-13"},
        headers=headers,
    ).json()
    template = client.get("/api/report-templates").json()[0]
    response = client.post(
        f"/api/prospects/{prospect['id']}/reports",
        json={
            "title": f"{name} Discovery",
            "report_template_id": template["id"],
            "site_id": site["id"],
            "engagement_id": engagement["id"],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    report = response.json()
    return report["id"], client.get(f"/api/reports/{report['id']}").json()


def test_section_questions_are_hidden_read_only_and_transient():
    js = (_root() / "app/static/app.js").read_text(encoding="utf-8")
    assert 'data-action="toggle-discovery-questions"' in js
    assert 'id="section-discovery-questions"' in js
    assert "Reference questions only. Responses are no longer entered or collected" in js
    assert 'class="prompt-answer"' not in js
    assert "schedulePromptSave" not in js
    assert "sectionPanelState: {screenId: null, discoveryQuestions: false, aiHistory: false}" in js
    assert "state.sectionPanelState.screenId !== screenId" in js
    assert "state.sectionPanelState = {screenId, discoveryQuestions:false, aiHistory:false}" in js


def test_demo_priority_is_removed_from_active_ui_and_ai_inputs():
    root = _root()
    js = (root / "app/static/app.js").read_text(encoding="utf-8")
    ai = (root / "app/ai_service.py").read_text(encoding="utf-8")
    readiness = (root / "app/readiness.py").read_text(encoding="utf-8")
    assert 'id="section-demo-priority-form"' not in js
    assert "demo-priority-summary" not in js
    assert "demoPriorityForSection" not in js
    assert "DemoSectionPriority" not in ai
    assert '"demo_priority"' not in ai
    assert "MUST_SHOW" not in ai
    assert "DO_NOT_SHOW" not in ai
    assert "DemoSectionPriority" not in readiness
    assert '"demo_priority"' not in readiness


def test_functional_mapping_display_is_removed_but_mapping_action_remains():
    js = (_root() / "app/static/app.js").read_text(encoding="utf-8")
    assert "Approved functionality mappings" not in js
    assert "Cloud Inventory functionality</h3>" not in js
    assert 'data-action="map-capability"' in js


def test_ai_assistance_is_replaced_by_transient_ai_history():
    js = (_root() / "app/static/app.js").read_text(encoding="utf-8")
    assert "AI assistance</h3>" not in js
    assert 'data-action="toggle-ai-history"' in js
    assert 'id="section-ai-history"' in js
    assert "Previous AI activity for this operational section" in js
    assert "item.review_state==='PENDING'&&canReviewHistory(item)" in js
    assert 'data-action="review-ai"' in js


def test_legacy_demo_priority_rows_do_not_feed_new_demo_snapshot(admin_session):
    from app.ai_service import build_demo_plan_snapshot
    from app.database import SessionLocal
    from app.models import Report

    client, me = admin_session
    report_id, report = _create_report(client, me)
    section = next(item for item in report["sections"] if item["process_module"] == "PICKING")
    saved = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/demo-priority",
        json={
            "priority": "MUST_SHOW",
            "user_notes": "Legacy hidden note",
            "constraints": "Legacy hidden constraint",
            "estimated_minutes": 17,
        },
        headers=_headers(me),
    )
    assert saved.status_code == 200, saved.text

    with SessionLocal() as db:
        snapshot = build_demo_plan_snapshot(db, db.get(Report, report_id))
    packet = next(item for item in snapshot["sections"] if item["id"] == section["id"])
    assert "priority" not in packet
    assert "user_notes" not in packet
    assert "constraints" not in packet
    assert "estimated_minutes" not in packet


def test_release_version_is_v0811_without_schema_change():
    root = _root()
    config = (root / "app/config.py").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    sw = (root / "app/static/sw.js").read_text(encoding="utf-8")
    assert 'app_version: str = "0.8.11"' in config
    assert 'version = "0.8.11"' in pyproject
    assert "ci-discovery-v0.8.11" in sw
    assert any("n94k7f3i1g54" in p.name for p in (root / "alembic/versions").glob("*.py"))
