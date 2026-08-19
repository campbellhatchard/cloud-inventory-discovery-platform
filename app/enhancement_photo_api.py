from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import require_report_access
from .ai_service import build_observation_snapshot, evaluate_policy, observation_source_fingerprint
from .audit import audit
from .auth import enforce_password_changed, require_csrf
from .config import Settings, get_settings
from .current_operations import sync_narrative_findings
from .database import get_db
from .jobs import enqueue
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


def _photo_status_payload(db: Session, report: Report, section: ReportSection) -> dict[str, Any]:
    records = _photo_records(db, report, section)
    valid_count = sum(1 for record in records if record["cache"])
    active_count = sum(1 for record in records if record["active_job"])
    all_analyzed = bool(records) and valid_count == len(records)

    current_fingerprint = None
    narrative_fingerprint = None
    if all_analyzed:
        current_fingerprint, narrative_fingerprint = _revision_fingerprint(section, records)

    latest_revision = db.scalar(
        select(AiSuggestion)
        .where(
            AiSuggestion.report_id == report.id,
            AiSuggestion.section_id == section.id,
            AiSuggestion.purpose == "PHOTO_CONTEXT_REVISION",
            AiSuggestion.review_state.in_(["PENDING", "APPROVED", "REJECTED"]),
        )
        .order_by(AiSuggestion.created_at.desc())
    )
    revision_job = db.scalar(
        select(AiJob)
        .where(
            AiJob.report_id == report.id,
            AiJob.section_id == section.id,
            AiJob.purpose == "PHOTO_CONTEXT_REVISION",
            AiJob.status.in_(["QUEUED", "RUNNING"]),
        )
        .order_by(AiJob.created_at.desc())
    )

    latest_content = dict((latest_revision.content or {}) if latest_revision else {})
    snapshot_photos = {
        str(item.get("evidence_id")): str(item.get("file_sha256") or "")
        for item in (latest_content.get("source_snapshot") or {}).get("photos") or []
        if item.get("evidence_id")
    }
    photos_unchanged = bool(records) and len(snapshot_photos) == len(records) and all(
        snapshot_photos.get(record["evidence"].id) == record["file_fingerprint"]
        for record in records
    )
    reviewed_current = False
    if latest_revision and latest_revision.review_state == "APPROVED" and photos_unchanged:
        reviewed_current = section.narrative.strip() == str(
            latest_content.get("suggested_text") or latest_content.get("enhanced_text") or ""
        ).strip()
    elif latest_revision and latest_revision.review_state == "REJECTED" and photos_unchanged:
        reviewed_current = narrative_fingerprint == latest_content.get("source_narrative_fingerprint")

    is_stale = bool(
        latest_revision
        and latest_revision.review_state == "PENDING"
        and current_fingerprint
        and latest_revision.source_fingerprint != current_fingerprint
    )
    current_pending_revision = bool(
        latest_revision
        and latest_revision.review_state == "PENDING"
        and not is_stale
    )
    if active_count or revision_job:
        overall = "ANALYZING"
    elif current_pending_revision:
        overall = "REVIEW_AVAILABLE"
    elif reviewed_current:
        overall = "REVIEWED"
    elif all_analyzed:
        overall = "ANALYSIS_COMPLETE"
    else:
        overall = "NOT_ANALYZED"

    photos = []
    for record in records:
        cache = record["cache"]
        analysis = dict((cache or {}).get("analysis") or {})
        photos.append(
            {
                "evidence_id": record["evidence"].id,
                "caption": record["evidence"].caption,
                "file_name": record["file"].file_name,
                "file_id": record["file"].id,
                "file_fingerprint": record["file_fingerprint"],
                "status": "ANALYZING" if record["active_job"] else ("ANALYZED" if cache else "NOT_ANALYZED"),
                "analysis": analysis if cache else None,
                "analyzed_at": (cache or {}).get("analyzed_at"),
                "active_job_id": record["active_job"].id if record["active_job"] else None,
            }
        )

    return {
        "status": overall,
        "photo_count": len(records),
        "analyzed_count": valid_count,
        "active_count": active_count,
        "can_request_revision": (
            all_analyzed
            and bool(section.narrative.strip())
            and not revision_job
            and not current_pending_revision
            and not reviewed_current
        ),
        "current_source_fingerprint": current_fingerprint,
        "current_narrative_fingerprint": narrative_fingerprint,
        "photos": photos,
        "revision_job_id": revision_job.id if revision_job else None,
        "latest_revision": _serialize_suggestion(latest_revision),
        "latest_revision_is_stale": is_stale,
    }


@router.get("/reports/{report_id}/sections/{section_id}/photo-intelligence")
def get_photo_intelligence(
    report_id: str,
    section_id: str,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, section_id)
    if section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")
    return _photo_status_payload(db, report, section)


@router.post(
    "/reports/{report_id}/sections/{section_id}/photo-intelligence/analyze",
    dependencies=[Depends(require_csrf)],
    status_code=status.HTTP_202_ACCEPTED,
)
def analyze_section_photos(
    report_id: str,
    section_id: str,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, section_id)
    if section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")

    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    if not decision.allowed:
        raise HTTPException(403, detail={"message": decision.reason, "policy": decision.as_dict()})

    records = _photo_records(db, report, section)
    if not records:
        raise HTTPException(409, "Add at least one photograph before running Photo Intelligence.")

    queued: list[str] = []
    reused: list[str] = []
    for record in records:
        if record["cache"]:
            reused.append(record["evidence"].id)
            continue
        if record["active_job"]:
            queued.append(record["active_job"].id)
            continue
        job = AiJob(
            report_id=report.id,
            section_id=section.id,
            purpose="PHOTO_ANALYSIS",
            instructions=None,
            model=settings.openai_analysis_model or settings.openai_model,
            policy_decision=decision.as_dict(),
            context_snapshot={
                "evidence_id": record["evidence"].id,
                "file_sha256": record["file_fingerprint"],
            },
            parent_suggestion_id=None,
            source_fingerprint=record["file_fingerprint"][:64],
            status="QUEUED",
            requested_by=user.id,
        )
        db.add(job)
        db.flush()
        enqueue(
            db,
            "ai.photo-analyze",
            {"ai_job_id": job.id},
            max_attempts=3,
            queue_name="PHOTO_AI",
            priority=20,
        )
        queued.append(job.id)

    audit(
        db,
        actor=user,
        action="PHOTO_INTELLIGENCE_QUEUED",
        target_type="REPORT_SECTION",
        target_id=section.id,
        prospect_id=report.prospect_id,
        metadata={"queued_jobs": queued, "cached_photos": reused},
    )
    db.commit()
    return {
        "status": "QUEUED" if queued else "ALREADY_ANALYZED",
        "queued_job_ids": queued,
        "cached_evidence_ids": reused,
    }


@router.post(
    "/reports/{report_id}/sections/{section_id}/photo-intelligence/revision",
    dependencies=[Depends(require_csrf)],
    status_code=status.HTTP_202_ACCEPTED,
)
def request_photo_revision(
    report_id: str,
    section_id: str,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, section_id)
    if section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")
    if not section.narrative.strip():
        raise HTTPException(409, "Enter Current Operations Narrative content before correlating photographs.")

    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    if not decision.allowed:
        raise HTTPException(403, detail={"message": decision.reason, "policy": decision.as_dict()})

    records = _photo_records(db, report, section)
    if not records:
        raise HTTPException(409, "Add at least one photograph before requesting a narrative revision.")
    if any(not record["cache"] for record in records):
        raise HTTPException(409, "Complete independent photo analysis before requesting a narrative revision.")

    fingerprint, narrative_fingerprint = _revision_fingerprint(section, records)
    existing = db.scalar(
        select(AiSuggestion)
        .where(
            AiSuggestion.report_id == report.id,
            AiSuggestion.section_id == section.id,
            AiSuggestion.purpose == "PHOTO_CONTEXT_REVISION",
            AiSuggestion.review_state == "PENDING",
            AiSuggestion.source_fingerprint == fingerprint,
        )
        .order_by(AiSuggestion.created_at.desc())
    )
    if existing:
        job = db.get(AiJob, existing.ai_job_id)
        if job:
            return _serialize_job(
                job,
                existing,
                reused=True,
                restored=True,
                message="Saved photo-context revision restored because neither the narrative nor photographs changed.",
            )

    active = db.scalar(
        select(AiJob)
        .where(
            AiJob.report_id == report.id,
            AiJob.section_id == section.id,
            AiJob.purpose == "PHOTO_CONTEXT_REVISION",
            AiJob.source_fingerprint == fingerprint,
            AiJob.status.in_(["QUEUED", "RUNNING"]),
        )
        .order_by(AiJob.created_at.desc())
    )
    if active:
        return _serialize_job(active, None, reused=True, restored=True)

    photos = [
        {
            "evidence_id": record["evidence"].id,
            "caption": record["evidence"].caption,
            "file_name": record["file"].file_name,
            "file_sha256": record["file_fingerprint"],
            "independent_visual_analysis": (record["cache"] or {}).get("analysis") or {},
        }
        for record in records
    ]
    snapshot = {
        "section": {
            "id": section.id,
            "title": section.title,
            "process_module": section.process_module,
        },
        "original_narrative": section.narrative,
        "source_section_version": section.version,
        "source_narrative_fingerprint": narrative_fingerprint,
        "photos": photos,
    }
    job = AiJob(
        report_id=report.id,
        section_id=section.id,
        purpose="PHOTO_CONTEXT_REVISION",
        instructions=None,
        model=settings.openai_analysis_model or settings.openai_model,
        policy_decision=decision.as_dict(),
        context_snapshot=snapshot,
        parent_suggestion_id=None,
        source_fingerprint=fingerprint,
        status="QUEUED",
        requested_by=user.id,
    )
    db.add(job)
    db.flush()
    enqueue(
        db,
        "ai.photo-revision",
        {"ai_job_id": job.id},
        max_attempts=3,
        queue_name="PHOTO_AI",
        priority=30,
    )
    audit(
        db,
        actor=user,
        action="PHOTO_CONTEXT_REVISION_QUEUED",
        target_type="AI_JOB",
        target_id=job.id,
        prospect_id=report.prospect_id,
        metadata={"section_id": section.id, "photo_count": len(photos), "source_fingerprint": fingerprint},
    )
    db.commit()
    return {
        "ai_job_id": job.id,
        "status": job.status,
        "message": "Photo analyses queued for correlation with the Current Operations Narrative.",
        "source_fingerprint": fingerprint,
    }

