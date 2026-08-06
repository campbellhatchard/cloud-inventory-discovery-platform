from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from docx import Document
from PIL import Image

from app.documents import _add_cover, _photo_dimensions_inches
from app.models import BrandingProfile, Engagement, Prospect, Report, Site

ROOT = Path(__file__).resolve().parents[1]


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me) -> tuple[str, str]:
    h = headers(me)
    prospect = client.post(
        "/api/prospects",
        json={"name": "v0.8.2 Usability Prospect", "industry": "Distribution", "opportunity": "Media workflow"},
        headers=h,
    )
    assert prospect.status_code == 200, prospect.text
    prospect_id = prospect.json()["id"]
    site = client.post(
        f"/api/prospects/{prospect_id}/sites",
        json={"name": "Main Warehouse", "address": "Kansas", "timezone": "America/Chicago"},
        headers=h,
    )
    engagement = client.post(
        f"/api/prospects/{prospect_id}/engagements",
        json={"name": "Usability Survey", "site_id": site.json()["id"], "survey_date": "2026-08-03"},
        headers=h,
    )
    template = client.get("/api/report-templates").json()[0]
    report = client.post(
        f"/api/prospects/{prospect_id}/reports",
        json={
            "title": "Usability Workflow Report",
            "engagement_id": engagement.json()["id"],
            "site_id": site.json()["id"],
            "report_template_id": template["id"],
            "report_kind": "CAPTURE",
        },
        headers=h,
    )
    assert report.status_code == 200, report.text
    return prospect_id, report.json()["id"]


def jpeg_bytes(size: tuple[int, int] = (420, 280)) -> bytes:
    image = Image.new("RGB", size, "white")
    output = io.BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


def test_v082_frontend_navigation_and_usability_contract() -> None:
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    assert 'data-action="open-overview"' in app_js
    assert 'data-action="open-report-preview"' in app_js
    assert 'data-action="open-demo-preparation"' in app_js
    assert app_js.index('data-action="open-overview"') < app_js.index('data-action="open-report-preview"')
    assert app_js.index('data-action="open-report-preview"') < app_js.index('data-action="open-demo-preparation"')
    assert "function overviewContent()" in app_js
    assert "function demoPreparationContent()" in app_js
    assert "Only the most recent publication for each document type is displayed." in app_js
    assert "function latestPublications" in app_js
    assert "state.activeAdminTab" in app_js
    assert "renderAdmin('capabilities')" in app_js
    assert "renderAdmin('knowledge')" in app_js
    assert 'class="report-prospect-logo"' in app_js
    assert 'data-action="open-evidence-preview"' in app_js
    assert 'data-action="move-selected-evidence"' in app_js
    assert 'data-action="delete-selected-evidence"' in app_js
    assert "state.reportFocusAnchor='photos'" in app_js
    assert "preview_file||item.file" in app_js or "preview_file || item.file" in app_js
    assert ".readiness-table table" in styles
    assert "table-layout: fixed" in styles
    assert ".file-preview-modal" in styles


def test_branding_photo_dimensions_can_be_configured(admin_session) -> None:
    client, me = admin_session
    branding = client.get("/api/admin/branding")
    assert branding.status_code == 200, branding.text
    brand = branding.json()
    payload = {
        "photo_size_uom": "CENTIMETRES",
        "landscape_photo_width": 15.5,
        "landscape_photo_height": 9.5,
        "portrait_photo_width": 9.5,
        "portrait_photo_height": 15.5,
    }
    updated = client.patch(
        f"/api/admin/branding/{brand['id']}",
        json=payload,
        headers=headers(me),
    )
    assert updated.status_code == 200, updated.text
    refreshed = client.get("/api/admin/branding").json()
    for key, value in payload.items():
        assert refreshed[key] == value


def test_photo_dimension_boxes_preserve_aspect_ratio() -> None:
    brand = BrandingProfile(
        name="Test",
        photo_size_uom="INCHES",
        landscape_photo_width=6.0,
        landscape_photo_height=4.0,
        portrait_photo_width=4.0,
        portrait_photo_height=6.0,
    )
    landscape = _photo_dimensions_inches(brand, 1200, 600)
    portrait = _photo_dimensions_inches(brand, 600, 1200)
    assert landscape == (6.0, 3.0)
    assert portrait == (3.0, 6.0)

    brand.photo_size_uom = "CENTIMETRES"
    brand.landscape_photo_width = 15.24
    brand.landscape_photo_height = 10.16
    cm_landscape = _photo_dimensions_inches(brand, 1200, 600)
    assert round(cm_landscape[0], 2) == 6.0
    assert round(cm_landscape[1], 2) == 3.0


def test_prospect_logo_is_supported_on_generated_cover(tmp_path: Path) -> None:
    logo = tmp_path / "logo.png"
    Image.new("RGB", (300, 100), "white").save(logo, "PNG")
    doc = Document()
    report = Report(title="Discovery", report_kind="CAPTURE", prospect_id="p", engagement_id="e", report_template_id="t", owner_id="u")
    prospect = Prospect(name="Prospect With Logo", industry="Distribution", opportunity="Test", created_by="u")
    site = Site(name="Warehouse", prospect_id="p", timezone="America/Chicago", created_by="u")
    engagement = Engagement(name="Survey", prospect_id="p", owner_id="u", survey_date=date(2026, 8, 3))
    brand = BrandingProfile(
        name="Default",
        primary_color="#22364A",
        secondary_color="#00A9CE",
        accent_color="#6B7785",
        heading_font="Aptos Display",
        body_font="Aptos",
        confidentiality_text="Confidential",
        draft_watermark="DRAFT",
        footer_text="",
    )

    _add_cover(doc, report, prospect, site, engagement, brand, logo, logo, False)

    assert "Prospect With Logo" in "\n".join(p.text for p in doc.paragraphs)
    assert len(doc.inline_shapes) == 2


def test_evidence_preview_move_and_delete_workflow(admin_session) -> None:
    client, me = admin_session
    _, report_id = create_report(client, me)
    report = client.get(f"/api/reports/{report_id}").json()
    receiving = next(item for item in report["sections"] if item["process_module"] == "RECEIVING")
    picking = next(item for item in report["sections"] if item["process_module"] == "PICKING")

    uploaded_ids: list[str] = []
    for index in range(2):
        uploaded = client.post(
            f"/api/reports/{report_id}/evidence",
            data={
                "section_id": receiving["id"],
                "caption": f"Receiving photograph {index + 1}",
                "placement": "INLINE",
                "classification": "CONFIDENTIAL",
            },
            files={"file": (f"receiving-{index + 1}.jpg", jpeg_bytes(), "image/jpeg")},
            headers=headers(me),
        )
        assert uploaded.status_code == 200, uploaded.text
        uploaded_ids.append(uploaded.json()["id"])

    refreshed = client.get(f"/api/reports/{report_id}").json()
    first = next(item for item in refreshed["evidence"] if item["id"] == uploaded_ids[0])
    assert first["file"]["variant"] == "ORIGINAL"
    assert first["preview_file"]["variant"] == "WEB"

    preview = client.get(f"/api/files/{first['preview_file']['id']}?inline=true")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/")
    assert preview.headers["content-disposition"].startswith("inline")

    moved = client.post(
        f"/api/reports/{report_id}/evidence/bulk",
        json={"action": "MOVE", "evidence_ids": uploaded_ids, "target_section_id": picking["id"]},
        headers=headers(me),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["affected_count"] == 2
    after_move = client.get(f"/api/reports/{report_id}").json()
    assert all(
        next(item for item in after_move["evidence"] if item["id"] == evidence_id)["section_id"] == picking["id"]
        for evidence_id in uploaded_ids
    )

    deleted = client.post(
        f"/api/reports/{report_id}/evidence/bulk",
        json={"action": "DELETE", "evidence_ids": [uploaded_ids[0]]},
        headers=headers(me),
    )
    assert deleted.status_code == 200, deleted.text
    after_delete = client.get(f"/api/reports/{report_id}").json()
    remaining_ids = {item["id"] for item in after_delete["evidence"]}
    assert uploaded_ids[0] not in remaining_ids
    assert uploaded_ids[1] in remaining_ids


def test_v082_migration_and_version_contract() -> None:
    migration = (ROOT / "alembic" / "versions" / "g27d0e6b4f77_usability_photo_workflow.py").read_text(encoding="utf-8")
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    assert 'down_revision = "f16c9d5a3e66"' in migration
    assert "photo_size_uom" in migration
    assert "landscape_photo_width" in migration
    assert "portrait_photo_height" in migration
    assert 'app_version: str = "0.8.10"' in config
