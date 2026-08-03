from __future__ import annotations

from sqlalchemy import select


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me, name: str = "Manual Solution Approach Prospect") -> tuple[str, dict]:
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


def test_manual_cloud_inventory_approach_is_versioned_and_reportable(admin_session):
    from app.database import SessionLocal
    from app.models import SectionContentVersion

    client, me = admin_session
    report_id, report = create_report(client, me)
    section = next(item for item in report["sections"] if item["process_module"] == "PICKING")
    request_headers = headers(me)

    first_text = (
        "Cloud Inventory can support this operation by presenting configured picking work "
        "to mobile users while the source system retains order ownership."
    )
    first = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/content",
        json={
            "content_type": "CLOUD_INVENTORY_APPROACH",
            "text": first_text,
            "expected_version": None,
        },
        headers=request_headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    assert first.json()["source_type"] == "USER"

    reloaded = client.get(f"/api/reports/{report_id}").json()
    target = next(item for item in reloaded["sections"] if item["id"] == section["id"])
    assert target["cloud_inventory_approach"]["text"] == first_text
    assert target["cloud_inventory_approach"]["source_type"] == "USER"

    second_text = first_text + " Supervisors can retain visibility of outstanding work."
    second = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/content",
        json={
            "content_type": "CLOUD_INVENTORY_APPROACH",
            "text": second_text,
            "expected_version": first.json()["version"],
        },
        headers=request_headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 2

    history = client.get(
        f"/api/reports/{report_id}/sections/{section['id']}/content-versions",
        params={"content_type": "CLOUD_INVENTORY_APPROACH"},
    )
    assert history.status_code == 200
    assert [item["version"] for item in history.json()] == [2, 1]
    assert history.json()[0]["is_current"] is True
    assert history.json()[1]["is_current"] is False

    with SessionLocal() as db:
        versions = list(
            db.scalars(
                select(SectionContentVersion)
                .where(
                    SectionContentVersion.report_id == report_id,
                    SectionContentVersion.section_id == section["id"],
                    SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH",
                )
                .order_by(SectionContentVersion.version)
            ).all()
        )
        assert [item.source_type for item in versions] == ["USER", "USER"]
        assert versions[-1].text == second_text


def test_manual_solution_approach_rejects_stale_content_version(admin_session):
    client, me = admin_session
    report_id, report = create_report(client, me, "Manual Solution Conflict")
    section = next(item for item in report["sections"] if item["process_module"] == "PICKING")
    request_headers = headers(me)

    first = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/content",
        json={"text": "Initial manually entered solution approach.", "expected_version": None},
        headers=request_headers,
    )
    assert first.status_code == 200

    second = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/content",
        json={"text": "Updated manually entered solution approach.", "expected_version": 1},
        headers=request_headers,
    )
    assert second.status_code == 200

    stale = client.put(
        f"/api/reports/{report_id}/sections/{section['id']}/content",
        json={"text": "Stale overwrite attempt.", "expected_version": 1},
        headers=request_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_version"] == 2
    assert stale.json()["detail"]["current_text"] == "Updated manually entered solution approach."


def test_solution_approach_editor_supports_manual_mapping_and_ai_paths():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="cloud-inventory-approach-editor"' in app_js
    assert "scheduleSolutionApproachSave" in app_js
    assert "flushSolutionApproachSave" in app_js
    assert 'data-action="map-capability"' in app_js
    assert 'data-action="generate-solution-approach"' in app_js
    assert "Type the Cloud Inventory approach directly" in app_js
