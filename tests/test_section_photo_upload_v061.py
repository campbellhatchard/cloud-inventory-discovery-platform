from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me) -> str:
    h = headers(me)
    prospect = client.post(
        "/api/prospects",
        json={"name": "Section Photo Upload Test", "industry": "Distribution", "opportunity": "Direct section evidence"},
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
        json={"name": "Photo Survey", "site_id": site.json()["id"], "survey_date": "2026-08-03"},
        headers=h,
    )
    template = client.get("/api/report-templates").json()[0]
    report = client.post(
        f"/api/prospects/{prospect_id}/reports",
        json={
            "title": "Section Photo Upload",
            "engagement_id": engagement.json()["id"],
            "site_id": site.json()["id"],
            "report_template_id": template["id"],
            "report_kind": "CAPTURE",
        },
        headers=h,
    )
    assert report.status_code == 200, report.text
    return report.json()["id"]


def test_section_photo_upload_frontend_contract() -> None:
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'data-action="section-upload-photo"' in app_js
    assert 'id="section-photo-form"' in app_js
    assert 'accept="image/*"' in app_js
    assert 'multiple required' in app_js
    assert "upload.append('section_id',targetSection.id)" in app_js
    assert "upload.append('placement','INLINE')" in app_js
    assert "upload.append('classification','CONFIDENTIAL')" in app_js
    assert "queueEvidence({reportId,sectionId:targetSection.id" in app_js
    assert "Add photo to this section" in app_js
    assert "Add photographs" in app_js


def test_photo_can_be_uploaded_directly_to_operational_section(admin_session) -> None:
    client, me = admin_session
    report_id = create_report(client, me)
    report = client.get(f"/api/reports/{report_id}").json()
    receiving = next(section for section in report["sections"] if section["process_module"] == "RECEIVING")

    image = Image.new("RGB", (320, 240), "white")
    output = io.BytesIO()
    image.save(output, "JPEG")

    response = client.post(
        f"/api/reports/{report_id}/evidence",
        data={
            "section_id": receiving["id"],
            "caption": "Receiving staging area",
            "placement": "INLINE",
            "classification": "CONFIDENTIAL",
        },
        files={"file": ("receiving-staging.jpg", output.getvalue(), "image/jpeg")},
        headers=headers(me),
    )
    assert response.status_code == 200, response.text

    refreshed = client.get(f"/api/reports/{report_id}").json()
    photo = next(item for item in refreshed["evidence"] if item["id"] == response.json()["id"])
    assert photo["section_id"] == receiving["id"]
    assert photo["evidence_type"] == "PHOTO"
    assert photo["placement"] == "INLINE"
    assert photo["caption"] == "Receiving staging area"
    assert photo["file"]["mime_type"].startswith("image/")
