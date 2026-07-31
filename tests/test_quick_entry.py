from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me) -> str:
    h = headers(me)
    prospect = client.post(
        "/api/prospects",
        json={"name": "Quick Entry Test", "industry": "Distribution", "opportunity": "Field capture"},
        headers=h,
    )
    prospect_id = prospect.json()["id"]
    site = client.post(
        f"/api/prospects/{prospect_id}/sites",
        json={"name": "Operations", "address": "Kansas", "timezone": "America/Chicago"},
        headers=h,
    )
    engagement = client.post(
        f"/api/prospects/{prospect_id}/engagements",
        json={"name": "Quick Entry Survey", "site_id": site.json()["id"], "survey_date": "2026-07-31"},
        headers=h,
    )
    template = client.get("/api/report-templates").json()[0]
    report = client.post(
        f"/api/prospects/{prospect_id}/reports",
        json={
            "title": "Quick Entry Site Discovery",
            "engagement_id": engagement.json()["id"],
            "site_id": site.json()["id"],
            "report_template_id": template["id"],
            "report_kind": "CAPTURE",
        },
        headers=h,
    )
    assert report.status_code == 200, report.text
    return report.json()["id"]


def test_quick_entry_frontend_contract() -> None:
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    assert "data-action=\"open-quick-entry\"" in app_js
    assert "id=\"quick-entry-note-form\"" in app_js
    assert "id=\"quick-entry-area\"" in app_js
    assert "capture=\"environment\"" in app_js
    assert "id=\"quick-entry-camera\"" in app_js
    assert "id=\"quick-entry-file\"" in app_js
    assert "name=\"placement\"" not in app_js
    assert "quick-capture-form" not in app_js
    assert "evidence-form" not in app_js
    assert "value:'OTHER', label:'Other'" in app_js
    assert "stable_key === 'general-observations'" in app_js
    assert ".quick-entry-note { min-height: 220px" in styles


def test_printing_and_other_destinations_receive_quick_capture(admin_session) -> None:
    client, me = admin_session
    report_id = create_report(client, me)
    report = client.get(f"/api/reports/{report_id}").json()
    printing = next(section for section in report["sections"] if section["process_module"] == "PRINTING")
    other = next(section for section in report["sections"] if section["stable_key"] == "general-observations")

    printing_capture = client.post(
        f"/api/reports/{report_id}/quick-capture",
        json={
            "section_id": printing["id"],
            "note": "Labels are printed from a workstation beside the packing line.",
            "finding_type": "OBSERVATION",
            "client_mutation_id": "33333333-3333-4333-8333-333333333333",
        },
        headers=headers(me),
    )
    assert printing_capture.status_code == 200, printing_capture.text

    other_capture = client.post(
        f"/api/reports/{report_id}/quick-capture",
        json={
            "section_id": other["id"],
            "note": "A cross-process observation not assigned to a named operational area.",
            "finding_type": "OBSERVATION",
            "client_mutation_id": "44444444-4444-4444-8444-444444444444",
        },
        headers=headers(me),
    )
    assert other_capture.status_code == 200, other_capture.text

    refreshed = client.get(f"/api/reports/{report_id}").json()
    findings = refreshed["findings"]
    assert any(f["section_id"] == printing["id"] and "Labels are printed" in f["statement"] for f in findings)
    assert any(f["section_id"] == other["id"] and "cross-process observation" in f["statement"] for f in findings)
