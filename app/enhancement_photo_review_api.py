from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import require_report_access
from .audit import audit
from .auth import enforce_password_changed, require_csrf
from .current_operations import sync_narrative_findings
from .database import get_db
from .models import (
    AiJob,
    AiSuggestion,
    EvidenceItem,
    FileObject,
    Report,
    ReportSection,
    SectionContentVersion,
    User,
    utcnow,
)

router = APIRouter(prefix="/api")


class FastWordingRequest(BaseModel):
    section_id: str
    instructions: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    parent_suggestion_id: str | None = None
    force_regenerate: bool = False


class PhotoRevisionReview(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    note: str | None = None


def _get_report(db: Session, report_id: str) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "Report not found.")
    return report


def _get_section(db: Session, section_id: str) -> ReportSection:
    section = db.get(ReportSection, section_id)
    if not section:
        raise HTTPException(404, "Section not found.")
    return section


def _serialize_suggestion(suggestion: AiSuggestion | None) -> dict[str, Any] | None:
    if not suggestion:
        return None
    return {
        "id": suggestion.id,
        "content": suggestion.content,
        "source_refs": suggestion.source_refs,
        "confidence": suggestion.confidence,
        "review_state": suggestion.review_state,
        "source_fingerprint": suggestion.source_fingerprint,
        "parent_suggestion_id": suggestion.parent_suggestion_id,
        "base_ai_text": suggestion.base_ai_text,
        "refinement_instruction": suggestion.refinement_instruction,
        "superseded_by_suggestion_id": suggestion.superseded_by_suggestion_id,
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        "reviewed_at": suggestion.reviewed_at.isoformat() if suggestion.reviewed_at else None,
    }


def _serialize_job(job: AiJob, suggestion: AiSuggestion | None = None, **extra: Any) -> dict[str, Any]:
    payload = {
        "id": job.id,
        "ai_job_id": job.id,
        "report_id": job.report_id,
        "section_id": job.section_id,
        "purpose": job.purpose,
        "status": job.status,
        "model": job.model,
        "policy_decision": job.policy_decision,
        "parent_suggestion_id": job.parent_suggestion_id,
        "source_fingerprint": job.source_fingerprint,
        "token_usage": job.token_usage,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "suggestion": _serialize_suggestion(suggestion),
    }
    payload.update(extra)
    return payload


def _current_pending_wording(
    db: Session,
    report_id: str,
    section_id: str,
    fingerprint: str,
) -> AiSuggestion | None:
    return db.scalar(
        select(AiSuggestion)
        .where(
            AiSuggestion.report_id == report_id,
            AiSuggestion.section_id == section_id,
            AiSuggestion.purpose == "OBSERVATION_ENHANCEMENT",
            AiSuggestion.review_state == "PENDING",
            AiSuggestion.source_fingerprint == fingerprint,
        )
        .order_by(AiSuggestion.created_at.desc())
    )


def _image_file(db: Session, evidence_id: str) -> FileObject | None:
    return db.scalar(
        select(FileObject)
        .where(FileObject.evidence_id == evidence_id)
        .order_by((FileObject.variant == "ORIGINAL").desc(), FileObject.created_at.asc())
    )


def _file_fingerprint(file_obj: FileObject) -> str:
    return file_obj.sha256 or f"file:{file_obj.id}:{file_obj.size_bytes}"


def _photo_records(db: Session, report: Report, section: ReportSection) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    evidence_items = list(
        db.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.report_id == report.id, EvidenceItem.section_id == section.id)
            .order_by(EvidenceItem.created_at.asc())
        ).all()
    )
    active_jobs = list(
        db.scalars(
            select(AiJob)
            .where(
                AiJob.report_id == report.id,
                AiJob.section_id == section.id,
                AiJob.purpose == "PHOTO_ANALYSIS",
                AiJob.status.in_(["QUEUED", "RUNNING"]),
            )
            .order_by(AiJob.created_at.desc())
        ).all()
    )
    for evidence in evidence_items:
        file_obj = _image_file(db, evidence.id)
        if not file_obj or not file_obj.mime_type.startswith("image/"):
            continue
        fingerprint = _file_fingerprint(file_obj)
        metadata = dict(evidence.ai_inclusion_recommendation or {})
        cached = dict(metadata.get("photo_intelligence") or {})
        valid = cached.get("status") == "COMPLETED" and cached.get("file_sha256") == fingerprint
        active = next(
            (
                job
                for job in active_jobs
                if str((job.context_snapshot or {}).get("evidence_id") or "") == evidence.id
                and str((job.context_snapshot or {}).get("file_sha256") or "") == fingerprint
            ),
            None,
        )
        records.append(
            {
                "evidence": evidence,
                "file": file_obj,
                "file_fingerprint": fingerprint,
                "cache": cached if valid else None,
                "active_job": active,
            }
        )
    return records


def _revision_fingerprint(section: ReportSection, records: list[dict[str, Any]]) -> tuple[str, str]:
    narrative_fingerprint = hashlib.sha256(section.narrative.strip().encode("utf-8")).hexdigest()
    photo_sources = []
    for record in records:
        cached = record.get("cache") or {}
        analysis = cached.get("analysis") or {}
        analysis_hash = hashlib.sha256(
            json.dumps(analysis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        photo_sources.append(
            {
                "evidence_id": record["evidence"].id,
                "file_fingerprint": record["file_fingerprint"],
                "analysis_hash": analysis_hash,
            }
        )
    canonical = {
        "section_id": section.id,
        "narrative_fingerprint": narrative_fingerprint,
        "photos": sorted(photo_sources, key=lambda item: item["evidence_id"]),
    }
    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return fingerprint, narrative_fingerprint


def _next_content_version(db: Session, section_id: str) -> int:
    value = db.scalar(
        select(func.max(SectionContentVersion.version)).where(
            SectionContentVersion.section_id == section_id,
            SectionContentVersion.content_type == "CURRENT_OPERATIONS",
        )
    )
    return int(value or 0) + 1


@router.post(
    "/reports/{report_id}/sections/{section_id}/photo-intelligence/revisions/{suggestion_id}/review",
    dependencies=[Depends(require_csrf)],
)
def review_photo_revision(
    report_id: str,
    section_id: str,
    suggestion_id: str,
    payload: PhotoRevisionReview,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, section_id)
    if section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")
    suggestion = db.get(AiSuggestion, suggestion_id)
    if (
        not suggestion
        or suggestion.report_id != report.id
        or suggestion.section_id != section.id
        or suggestion.purpose != "PHOTO_CONTEXT_REVISION"
    ):
        raise HTTPException(404, "Photo-context revision not found.")
    if suggestion.review_state != "PENDING":
        raise HTTPException(409, "This photo-context revision has already been reviewed.")

    content = dict(suggestion.content or {})
    if payload.decision == "APPROVED":
        if content.get("verification_status") != "PASSED" or not content.get("accept_allowed", False):
            raise HTTPException(409, "This photo-context revision is not verified and cannot be accepted.")
        records = _photo_records(db, report, section)
        if not records or any(not record["cache"] for record in records):
            raise HTTPException(409, "Photo analysis changed or is incomplete. Generate a new revision.")
        current_fingerprint, _ = _revision_fingerprint(section, records)
        if current_fingerprint != suggestion.source_fingerprint:
            raise HTTPException(
                409,
                "The Current Operations Narrative or photographs changed after this revision was generated. Generate a new revision.",
            )
        suggested_text = str(content.get("suggested_text") or content.get("enhanced_text") or "").strip()
        if not suggested_text:
            raise HTTPException(409, "The revision does not contain usable text.")

        for current in db.scalars(
            select(SectionContentVersion).where(
                SectionContentVersion.section_id == section.id,
                SectionContentVersion.content_type == "CURRENT_OPERATIONS",
                SectionContentVersion.is_current.is_(True),
            )
        ).all():
            current.is_current = False

        original = str(content.get("original_text") or section.narrative or "")
        existing_original = db.scalar(
            select(SectionContentVersion)
            .where(
                SectionContentVersion.section_id == section.id,
                SectionContentVersion.content_type == "CURRENT_OPERATIONS",
                SectionContentVersion.text == original,
            )
            .order_by(SectionContentVersion.version.desc())
        )
        if not existing_original:
            db.add(
                SectionContentVersion(
                    report_id=report.id,
                    section_id=section.id,
                    content_type="CURRENT_OPERATIONS",
                    version=_next_content_version(db, section.id),
                    text=original,
                    source_type="USER",
                    source_refs=[],
                    is_current=False,
                    created_by=user.id,
                )
            )
            db.flush()

        db.add(
            SectionContentVersion(
                report_id=report.id,
                section_id=section.id,
                content_type="CURRENT_OPERATIONS",
                version=_next_content_version(db, section.id),
                text=suggested_text,
                source_type="AI_PHOTO_ACCEPTED",
                source_refs=content.get("source_refs") or [],
                ai_suggestion_id=suggestion.id,
                is_current=True,
                created_by=user.id,
            )
        )
        section.narrative = suggested_text
        sync_narrative_findings(db, report_id=report.id, section=section, actor_user_id=user.id)
        section.version += 1
        section.updated_by = user.id
        report.revision += 1

    suggestion.review_state = payload.decision
    suggestion.reviewed_by = user.id
    suggestion.review_note = payload.note
    suggestion.reviewed_at = utcnow()
    audit(
        db,
        actor=user,
        action="PHOTO_CONTEXT_REVISION_REVIEWED",
        target_type="AI_SUGGESTION",
        target_id=suggestion.id,
        prospect_id=report.prospect_id,
        metadata={"decision": payload.decision, "section_id": section.id},
    )
    db.commit()
    return {
        "ok": True,
        "decision": payload.decision,
        "narrative_updated": payload.decision == "APPROVED",
        "section_version": section.version,
        "report_revision": report.revision,
    }
