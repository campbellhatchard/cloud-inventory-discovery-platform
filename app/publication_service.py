from __future__ import annotations

from sqlalchemy.orm import Session

from .config import Settings
from .documents import convert_docx_to_pdf, generate_docx, refresh_docx_fields
from .models import FileObject, Publication, Report, utcnow
from .storage import ObjectStorage, build_storage_key


def process_publication(db: Session, publication_id: str, settings: Settings) -> Publication:
    publication = db.get(Publication, publication_id)
    if not publication:
        raise ValueError("Publication not found")
    report = db.get(Report, publication.report_id)
    if not report:
        raise ValueError("Report not found")
    publication.status = "GENERATING"
    db.commit()
    try:
        docx_bytes = generate_docx(db, report.id, settings, publication_type=publication.publication_type, is_final=publication.is_final)
        docx_bytes, pdf_bytes = refresh_docx_fields(docx_bytes, settings, emit_pdf=True)
        if pdf_bytes is None:
            pdf_bytes = convert_docx_to_pdf(docx_bytes, settings)
        storage = ObjectStorage(settings)
        stem = "-".join("".join(c if c.isalnum() else " " for c in report.title).split())[:90] or "site-discovery-report"
        suffix = "final" if publication.is_final else "draft"
        docx_name = f"{stem}-r{publication.report_revision}-{suffix}.docx"
        pdf_name = f"{stem}-r{publication.report_revision}-{suffix}.pdf"
        docx_key = build_storage_key(report.prospect_id, "publications", publication.id, docx_name)
        pdf_key = build_storage_key(report.prospect_id, "publications", publication.id, pdf_name)
        stored_docx = storage.put_bytes(docx_key, docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        stored_pdf = storage.put_bytes(pdf_key, pdf_bytes, "application/pdf")
        docx_obj = FileObject(prospect_id=report.prospect_id, storage_key=stored_docx.key, variant="PUBLICATION_DOCX", file_name=docx_name, mime_type=stored_docx.mime_type, size_bytes=stored_docx.size, sha256=stored_docx.sha256, scan_state="GENERATED")
        pdf_obj = FileObject(prospect_id=report.prospect_id, storage_key=stored_pdf.key, variant="PUBLICATION_PDF", file_name=pdf_name, mime_type=stored_pdf.mime_type, size_bytes=stored_pdf.size, sha256=stored_pdf.sha256, scan_state="GENERATED")
        db.add_all([docx_obj, pdf_obj])
        db.flush()
        publication.docx_file_id = docx_obj.id
        publication.pdf_file_id = pdf_obj.id
        publication.status = "COMPLETED"
        publication.completed_at = utcnow()
        publication.error = None
        if publication.is_final:
            report.state = "FINALIZED"
        db.commit()
        return publication
    except Exception as exc:
        publication.status = "FAILED"
        publication.error = str(exc)[:10000]
        publication.completed_at = utcnow()
        db.commit()
        raise
