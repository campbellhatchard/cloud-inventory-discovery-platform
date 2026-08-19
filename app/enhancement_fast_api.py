from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import require_report_access
from .ai_service import build_observation_snapshot, evaluate_policy, observation_source_fingerprint
from .audit import audit
from .auth import enforce_password_changed, require_csrf
from .config import Settings, get_settings
from .database import get_db
from .jobs import enqueue
from .models import AiJob, AiSuggestion, Report, ReportSection, User

router = APIRouter(prefix="/api")


class FastWordingRequest(BaseModel):
    section_id: str
    instructions: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    parent_suggestion_id: str | None = None
    force_regenerate: bool = False


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


@router.post(
    "/reports/{report_id}/ai-fast-wording",
    dependencies=[Depends(require_csrf)],
    status_code=status.HTTP_202_ACCEPTED,
)
def request_fast_wording(
    report_id: str,
    payload: FastWordingRequest,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, payload.section_id)
    if section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")
    if payload.evidence_ids:
        raise HTTPException(400, "Fast AI wording accepts written discovery only. Photo Intelligence is a separate workflow.")

    snapshot = build_observation_snapshot(db, report, section, [])
    fingerprint = str(snapshot.get("source_fingerprint") or observation_source_fingerprint(snapshot))
    snapshot["source_fingerprint"] = fingerprint

    parent: AiSuggestion | None = None
    if payload.parent_suggestion_id:
        parent = db.get(AiSuggestion, payload.parent_suggestion_id)
        if (
            not parent
            or parent.report_id != report.id
            or parent.section_id != section.id
            or parent.purpose != "OBSERVATION_ENHANCEMENT"
        ):
            raise HTTPException(400, "Parent AI wording does not belong to this report section.")
        if parent.review_state != "PENDING":
            raise HTTPException(409, "Only the active pending AI wording can be refined.")
        if not (payload.instructions or "").strip():
            raise HTTPException(400, "Enter a refinement request before refining the AI wording.")
        parent_fingerprint = str(parent.source_fingerprint or (parent.content or {}).get("source_fingerprint") or "")
        if parent_fingerprint != fingerprint:
            raise HTTPException(
                409,
                "The written Current Operations sources changed after this wording was created. Generate updated wording first.",
            )
    elif not payload.force_regenerate:
        existing = _current_pending_wording(db, report.id, section.id, fingerprint)
        if existing:
            existing_job = db.get(AiJob, existing.ai_job_id)
            if existing_job:
                return _serialize_job(
                    existing_job,
                    existing,
                    reused=True,
                    restored=True,
                    message="Saved AI wording restored because the written source content has not changed.",
                )
        active = db.scalar(
            select(AiJob)
            .where(
                AiJob.report_id == report.id,
                AiJob.section_id == section.id,
                AiJob.purpose == "OBSERVATION_ENHANCEMENT",
                AiJob.parent_suggestion_id.is_(None),
                AiJob.source_fingerprint == fingerprint,
                AiJob.status.in_(["QUEUED", "RUNNING", "VERIFYING"]),
            )
            .order_by(AiJob.created_at.desc())
        )
        if active:
            active_suggestion = db.scalar(
                select(AiSuggestion).where(AiSuggestion.ai_job_id == active.id).order_by(AiSuggestion.created_at.desc())
            )
            return _serialize_job(
                active,
                active_suggestion,
                reused=True,
                restored=True,
                message="The existing fast AI wording request is still processing.",
            )

    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    job = AiJob(
        report_id=report.id,
        section_id=section.id,
        purpose="OBSERVATION_ENHANCEMENT",
        instructions=payload.instructions,
        model=settings.openai_fast_text_model or settings.openai_model,
        policy_decision=decision.as_dict(),
        context_snapshot=snapshot,
        parent_suggestion_id=parent.id if parent else None,
        source_fingerprint=fingerprint,
        status="BLOCKED" if not decision.allowed else "QUEUED",
        requested_by=user.id,
    )
    db.add(job)
    db.flush()
    if not decision.allowed:
        audit(
            db,
            actor=user,
            action="AI_REQUEST_BLOCKED",
            target_type="AI_JOB",
            target_id=job.id,
            prospect_id=report.prospect_id,
            metadata=decision.as_dict(),
        )
        db.commit()
        raise HTTPException(
            403,
            detail={"message": decision.reason, "ai_job_id": job.id, "policy": decision.as_dict()},
        )

    enqueue(
        db,
        "ai.fast-wording",
        {"ai_job_id": job.id},
        max_attempts=3,
        queue_name="FAST_TEXT",
        priority=5,
    )
    audit(
        db,
        actor=user,
        action="AI_FAST_WORDING_QUEUED",
        target_type="AI_JOB",
        target_id=job.id,
        prospect_id=report.prospect_id,
        metadata={
            "purpose": job.purpose,
            "parent_suggestion_id": parent.id if parent else None,
            "source_fingerprint": fingerprint,
            "model": job.model,
        },
    )
    db.commit()
    return {
        "ai_job_id": job.id,
        "status": job.status,
        "message": "Fast text-only AI wording queued. Verification will continue independently.",
        "reused": False,
        "restored": False,
        "source_fingerprint": fingerprint,
    }
