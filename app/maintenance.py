from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import audit
from .config import Settings
from .models import EvidenceItem, FileObject, Prospect, Publication, Report, utcnow
from .storage import ObjectStorage


def mark_retention_reviews(db: Session, settings: Settings) -> int:
    cutoff = utcnow() + timedelta(days=settings.retention_warning_days)
    prospects = list(
        db.scalars(
            select(Prospect).where(
                Prospect.status == "ACTIVE",
                Prospect.legal_hold.is_(False),
                Prospect.retention_due_at <= cutoff,
            )
        ).all()
    )
    for prospect in prospects:
        prospect.status = "RETENTION_REVIEW"
        prospect.archive_prompted_at = prospect.archive_prompted_at or utcnow()
        audit(
            db,
            actor=None,
            action="RETENTION_REVIEW_DUE",
            target_type="PROSPECT",
            target_id=prospect.id,
            prospect_id=prospect.id,
            metadata={"retention_due_at": prospect.retention_due_at.isoformat()},
        )
    return len(prospects)


def purge_expired_merged_reports(db: Session, settings: Settings) -> int:
    storage = ObjectStorage(settings)
    reports = list(
        db.scalars(
            select(Report).where(
                Report.state == "MERGED",
                Report.recovery_delete_after.is_not(None),
                Report.recovery_delete_after <= utcnow(),
            )
        ).all()
    )
    deleted = 0
    for report in reports:
        evidence_ids = list(db.scalars(select(EvidenceItem.id).where(EvidenceItem.report_id == report.id)).all())
        evidence_files = list(db.scalars(select(FileObject).where(FileObject.evidence_id.in_(evidence_ids))).all()) if evidence_ids else []
        publications = list(db.scalars(select(Publication).where(Publication.report_id == report.id)).all())
        publication_file_ids = {file_id for item in publications for file_id in (item.docx_file_id, item.pdf_file_id) if file_id}
        publication_files = list(db.scalars(select(FileObject).where(FileObject.id.in_(publication_file_ids))).all()) if publication_file_ids else []
        all_files = {item.id: item for item in evidence_files + publication_files}
        for file_obj in all_files.values():
            try:
                storage.delete(file_obj.storage_key)
            except FileNotFoundError:
                pass
        prospect_id = report.prospect_id
        report_id = report.id
        title = report.title
        db.delete(report)
        db.flush()
        for file_obj in publication_files:
            if db.get(FileObject, file_obj.id):
                db.delete(file_obj)
        audit(
            db,
            actor=None,
            action="MERGED_SOURCE_PURGED",
            target_type="REPORT",
            target_id=report_id,
            prospect_id=prospect_id,
            metadata={"title": title, "files_deleted": len(all_files)},
        )
        deleted += 1
    return deleted


def run_maintenance(db: Session, settings: Settings) -> dict[str, int]:
    result = {
        "retention_reviews_marked": mark_retention_reviews(db, settings),
        "merged_reports_purged": purge_expired_merged_reports(db, settings),
    }
    db.commit()
    return result
