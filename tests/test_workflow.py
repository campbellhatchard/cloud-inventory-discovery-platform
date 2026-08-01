from __future__ import annotations

import io
import zipfile

from PIL import Image, ImageDraw

from app.database import SessionLocal
from app.models import Publication
from app.publication_service import process_publication
from app.config import get_settings


def headers(me: dict) -> dict[str, str]:
    return {"X-CSRF-Token": me["csrf_token"]}


def create_report(client, me):
    h = headers(me)
    prospect = client.post("/api/prospects", json={"name": "DIA Test", "industry": "Aviation MRO", "opportunity": "Warehouse and materials discovery"}, headers=h)
    assert prospect.status_code == 200, prospect.text
    prospect_id = prospect.json()["id"]
    site = client.post(f"/api/prospects/{prospect_id}/sites", json={"name": "MRO Stores", "address": "Denver, CO", "timezone": "America/Denver"}, headers=h)
    assert site.status_code == 200
    site_id = site.json()["id"]
    engagement = client.post(f"/api/prospects/{prospect_id}/engagements", json={"name": "Onsite Survey", "site_id": site_id, "survey_date": "2026-07-30", "objectives": "Assess current practices"}, headers=h)
    assert engagement.status_code == 200
    template = client.get("/api/report-templates").json()[0]
    report = client.post(f"/api/prospects/{prospect_id}/reports", json={"title": "DIA Site Discovery Report", "engagement_id": engagement.json()["id"], "site_id": site_id, "report_template_id": template["id"], "report_kind": "CONSOLIDATED"}, headers=h)
    assert report.status_code == 200, report.text
    return prospect_id, report.json()["id"]


def test_full_capture_and_document_generation(admin_session):
    client, me = admin_session
    h = headers(me)
    prospect_id, report_id = create_report(client, me)
    report = client.get(f"/api/reports/{report_id}")
    assert report.status_code == 200
    payload = report.json()
    assert len(payload["sections"]) == 31
    receiving = next(s for s in payload["sections"] if s["process_module"] == "RECEIVING")
    printing = next(s for s in payload["sections"] if s["process_module"] == "PRINTING")
    assert printing["title"] == "Printing"
    assert len(payload["prompts_by_module"]["PRINTING"]) == 18
    prompts = payload["prompts_by_module"]["RECEIVING"]

    response = client.put(
        f"/api/reports/{report_id}/sections/{receiving['id']}/responses",
        json={"prompt_id": prompts[0]["id"], "narrative": "Receive purchase-order materials at two dock doors.", "client_mutation_id": "11111111-1111-4111-8111-111111111111"},
        headers=h,
    )
    assert response.status_code == 200
    duplicate = client.put(
        f"/api/reports/{report_id}/sections/{receiving['id']}/responses",
        json={"prompt_id": prompts[0]["id"], "narrative": "Duplicate", "client_mutation_id": "11111111-1111-4111-8111-111111111111"},
        headers=h,
    )
    assert duplicate.status_code == 200
    assert duplicate.json().get("deduplicated") is True

    finding = client.post(
        f"/api/reports/{report_id}/quick-capture",
        json={"section_id": receiving["id"], "note": "Receipts are first recorded on paper and then entered at a desktop.", "finding_type": "PAIN_POINT", "impact": "Inventory visibility is delayed.", "client_mutation_id": "22222222-2222-4222-8222-222222222222"},
        headers=h,
    )
    assert finding.status_code == 200

    image = Image.new("RGB", (1000, 700), "#e8eef2")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 100, 920, 600), outline="#1f3447", width=10)
    draw.text((120, 150), "Receiving Dock", fill="#1f3447")
    output = io.BytesIO()
    image.save(output, "JPEG")
    evidence = client.post(
        f"/api/reports/{report_id}/evidence",
        data={"section_id": receiving["id"], "caption": "Receiving dock and staging area", "placement": "INLINE", "classification": "CONFIDENTIAL"},
        files={"file": ("receiving-dock.jpg", output.getvalue(), "image/jpeg")},
        headers=h,
    )
    assert evidence.status_code == 200, evidence.text
    refreshed = client.get(f"/api/reports/{report_id}").json()
    refreshed_receiving = next(s for s in refreshed["sections"] if s["id"] == receiving["id"])
    assert refreshed_receiving["state"] == "ACTIVE"

    validation = client.post(f"/api/reports/{report_id}/validate", json={"final_requested": False}, headers=h)
    assert validation.status_code == 200
    assert validation.json()["passed"] is True
    assert any(issue["code"] == "FINDING_UNADDRESSED" for issue in validation.json()["issues"])

    publication = client.post(f"/api/reports/{report_id}/publications", json={"publication_type": "FULL_DISCOVERY", "is_final": False}, headers=h)
    assert publication.status_code == 200, publication.text
    publication_id = publication.json()["id"]
    with SessionLocal() as db:
        process_publication(db, publication_id, get_settings())
        pub = db.get(Publication, publication_id)
        assert pub and pub.status == "COMPLETED"
        docx_id, pdf_id = pub.docx_file_id, pub.pdf_file_id

    docx = client.get(f"/api/files/{docx_id}")
    pdf = client.get(f"/api/files/{pdf_id}")
    assert docx.status_code == 200 and len(docx.content) > 20_000
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    with zipfile.ZipFile(io.BytesIO(docx.content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        header_xml = "".join(archive.read(name).decode("utf-8") for name in archive.namelist() if name.startswith("word/header") and name.endswith(".xml"))
        assert "DIA Site Discovery Report" in document_xml
        assert "Receiving dock and staging area" in document_xml
        assert "DRAFT - CONFIDENTIAL" in header_xml


def test_final_publication_allows_empty_optional_sections(admin_session):
    client, me = admin_session
    _, report_id = create_report(client, me)
    ready = client.patch(f"/api/reports/{report_id}", json={"state": "READY_FOR_REVIEW"}, headers=headers(me))
    assert ready.status_code == 200, ready.text
    response = client.post(f"/api/reports/{report_id}/publications", json={"publication_type": "FULL_DISCOVERY", "is_final": True}, headers=headers(me))
    assert response.status_code == 200, response.text
    validation = response.json()["validation"]
    assert validation["passed"] is True
    assert not any(issue["code"] in {"REQUIRED_SECTION_EMPTY", "REQUIRED_PROMPT_UNANSWERED"} for issue in validation["issues"])
