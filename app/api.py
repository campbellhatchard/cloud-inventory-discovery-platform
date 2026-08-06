from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response as FastAPIResponse, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from PIL import Image, ImageOps
from starlette.background import BackgroundTask
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .access import accessible_prospect_ids, require_prospect_access, require_report_access
from .ai_service import (
    build_demo_plan_snapshot,
    build_executive_summary_snapshot,
    build_observation_snapshot,
    observation_source_fingerprint,
    build_report_quality_snapshot,
    build_solution_snapshot,
    build_targeted_benefits_snapshot,
    evaluate_policy,
)
from .audit import audit
from .auth import (
    authenticate,
    clear_session_cookie,
    create_session,
    enforce_password_changed,
    get_current_session,
    get_current_user,
    hash_password,
    logout_session,
    require_csrf,
    require_roles,
    set_session_cookie,
    user_roles,
    verify_password,
)
from .config import Settings, get_settings
from .current_operations import (
    CURRENT_FINDING_EXCLUDED_STATUSES,
    NARRATIVE_DERIVED_SOURCE,
    append_narrative_entry,
    normalize_finding_type,
    sync_narrative_findings,
)
from .configuration_intelligence import CONFIGURATION_KNOWLEDGE_KIND, CONFIGURATION_SOURCE_TYPE, load_configuration_template, normalize_configuration_template
from .database import get_db
from .extraction import extract_text
from .jobs import enqueue
from .models import (
    AiJob,
    AiSuggestion,
    Approval,
    AuditEvent,
    Benefit,
    BrandingProfile,
    Capability,
    CapabilityMapping,
    Comment,
    DemoPlanSettings,
    DemoPlanVersion,
    DemoSectionPriority,
    Engagement,
    EngagementMember,
    EvidenceItem,
    FileObject,
    Finding,
    MergeLineage,
    MergeOperation,
    Metric,
    KnowledgeEntry,
    Prospect,
    ProspectMembership,
    PromptDefinition,
    Publication,
    Report,
    ReportContentVersion,
    ReportMember,
    ReportSection,
    ReportTemplate,
    Response,
    SectionContentVersion,
    SectionTemplate,
    Site,
    User,
    UserRole,
    UserSession,
    ValidationRun,
    utcnow,
)
from .schemas import (
    AiRequest,
    BenefitCreate,
    BrandingUpdate,
    DemoPlanSettingsUpsert,
    DemoSectionPriorityUpsert,
    CapabilityCreate,
    CapabilityMappingCreate,
    CapabilityUpdate,
    CommentCreate,
    EngagementCreate,
    EvidenceBulkAction,
    EvidenceReviewRequest,
    FindingCreate,
    LoginRequest,
    KnowledgeEntryCreate,
    KnowledgeEntryReview,
    MergeRequest,
    MetricCreate,
    AdminUserRolesUpdate,
    AdminUserStatusUpdate,
    PasswordChangeRequest,
    ProspectArchiveRequest,
    ProspectCreate,
    ProspectOnboardingCreate,
    ProspectDeleteRequest,
    PublicationRequest,
    QuickCaptureRequest,
    ReportContentUpsert,
    ReportCreate,
    ReportUpdate,
    ReportDeleteRequest,
    ResponseUpsert,
    ReviewDecision,
    SectionContentUpsert,
    SectionCreate,
    SectionUpdate,
    SiteCreate,
    UserCreate,
    ValidationRequest,
)
from .storage import ObjectStorage, StorageConfigurationError, build_storage_key, safe_filename, storage_configuration_status
from .usernames import normalize_username
from .readiness import (
    calculate_admin_operations,
    calculate_admin_review_queue,
    calculate_report_readiness,
    calculate_review_queue,
    calculate_traceability,
)
from .validation import validate_report, validation_passed
from .documents import convert_docx_to_pdf, generate_docx, refresh_docx_fields

router = APIRouter(prefix="/api")


def _iso(value):
    return value.isoformat() if value else None


def _observation_suggestion_fingerprint(suggestion: AiSuggestion) -> str | None:
    content = dict(suggestion.content or {})
    fingerprint = str(suggestion.source_fingerprint or content.get("source_fingerprint") or "").strip()
    if not fingerprint:
        snapshot = dict(content.get("source_snapshot") or {})
        if snapshot:
            fingerprint = observation_source_fingerprint(snapshot)
    if fingerprint and suggestion.source_fingerprint != fingerprint:
        suggestion.source_fingerprint = fingerprint
    return fingerprint or None


def _serialize_ai_suggestion(suggestion: AiSuggestion | None) -> dict[str, Any] | None:
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
        "created_at": _iso(suggestion.created_at),
        "reviewed_at": _iso(suggestion.reviewed_at),
    }


def _serialize_ai_job(job: AiJob, suggestion: AiSuggestion | None = None, **extra: Any) -> dict[str, Any]:
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
        "created_at": _iso(job.created_at),
        "completed_at": _iso(job.completed_at),
        "suggestion": _serialize_ai_suggestion(suggestion),
    }
    payload.update(extra)
    return payload


def _find_current_observation_suggestion(
    db: Session,
    report_id: str,
    section_id: str,
    source_fingerprint: str,
) -> AiSuggestion | None:
    candidates = list(
        db.scalars(
            select(AiSuggestion)
            .where(
                AiSuggestion.report_id == report_id,
                AiSuggestion.section_id == section_id,
                AiSuggestion.purpose == "OBSERVATION_ENHANCEMENT",
                AiSuggestion.review_state == "PENDING",
            )
            .order_by(AiSuggestion.created_at.desc())
        ).all()
    )
    for suggestion in candidates:
        if _observation_suggestion_fingerprint(suggestion) == source_fingerprint:
            return suggestion
    return None


def _find_latest_stale_observation_suggestion(
    db: Session,
    report_id: str,
    section_id: str,
    source_fingerprint: str,
) -> AiSuggestion | None:
    candidates = list(
        db.scalars(
            select(AiSuggestion)
            .where(
                AiSuggestion.report_id == report_id,
                AiSuggestion.section_id == section_id,
                AiSuggestion.purpose == "OBSERVATION_ENHANCEMENT",
                AiSuggestion.review_state.in_(["PENDING", "STALE"]),
            )
            .order_by(AiSuggestion.created_at.desc())
        ).all()
    )
    for suggestion in candidates:
        if _observation_suggestion_fingerprint(suggestion) != source_fingerprint:
            return suggestion
    return None


def _user_payload(db: Session, user: User, csrf_token: str | None = None) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "roles": sorted(user_roles(db, user.id)),
        "force_password_change": user.force_password_change,
        "csrf_token": csrf_token,
    }


def _get_report(db: Session, report_id: str) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report


def _get_section(db: Session, section_id: str) -> ReportSection:
    section = db.get(ReportSection, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")
    return section


def _increment_report(report: Report) -> None:
    report.revision += 1


def _next_content_version(db: Session, section_id: str, content_type: str = "CURRENT_OPERATIONS") -> int:
    current = db.scalar(
        select(func.max(SectionContentVersion.version)).where(
            SectionContentVersion.section_id == section_id,
            SectionContentVersion.content_type == content_type,
        )
    )
    return int(current or 0) + 1


def _next_report_content_version(db: Session, report_id: str, content_type: str) -> int:
    current = db.scalar(
        select(func.max(ReportContentVersion.version)).where(
            ReportContentVersion.report_id == report_id,
            ReportContentVersion.content_type == content_type,
        )
    )
    return int(current or 0) + 1


def _next_demo_plan_version(db: Session, report_id: str) -> int:
    current = db.scalar(select(func.max(DemoPlanVersion.version)).where(DemoPlanVersion.report_id == report_id))
    return int(current or 0) + 1


def _resolve_benefit_source(
    db: Session,
    report: Report,
    *,
    section_id: str | None,
    finding_id: str | None,
    capability_mapping_id: str | None,
    source_ref: str | None,
) -> dict[str, Any]:
    if capability_mapping_id:
        mapping = db.get(CapabilityMapping, capability_mapping_id)
        if not mapping or mapping.report_id != report.id:
            raise HTTPException(400, "Capability mapping is not available in this report.")
        capability = db.get(Capability, mapping.capability_id)
        return {
            "section_id": mapping.section_id,
            "finding_id": mapping.finding_id,
            "capability_mapping_id": mapping.id,
            "source_ref": f"mapping:{mapping.id}",
            "source_type": "CAPABILITY_MAPPING",
            "source_label": f"{capability.capability_code} — {capability.name}" if capability else (mapping.source_label or "Approved capability mapping"),
            "source_statement": mapping.rationale,
        }
    ref = (source_ref or "").strip()
    if finding_id or ref.startswith("finding:") or ref == "section:narrative" or ref.startswith("response:"):
        source = _resolve_mapping_source(
            db,
            report,
            section_id=section_id,
            source_ref=ref or None,
            finding_id=finding_id,
        )
        source["capability_mapping_id"] = None
        return source
    if ref.startswith("metric:"):
        metric = db.get(Metric, ref.split(":", 1)[1])
        if not metric or metric.report_id != report.id or (section_id and metric.section_id != section_id):
            raise HTTPException(400, "Metric is not available in the selected section.")
        value = metric.value_text if metric.value_text is not None else metric.value_numeric
        statement = f"{metric.name}: {value if value is not None else 'value not recorded'}{f' {metric.unit}' if metric.unit else ''}"
        return {
            "section_id": metric.section_id,
            "finding_id": None,
            "capability_mapping_id": None,
            "source_ref": ref,
            "source_type": "METRIC",
            "source_label": metric.name,
            "source_statement": statement,
        }
    if ref.startswith("solution:"):
        solution = db.get(SectionContentVersion, ref.split(":", 1)[1])
        if (
            not solution
            or solution.report_id != report.id
            or solution.content_type != "CLOUD_INVENTORY_APPROACH"
            or (section_id and solution.section_id != section_id)
        ):
            raise HTTPException(400, "Cloud Inventory approach source is not available in this section.")
        return {
            "section_id": solution.section_id,
            "finding_id": None,
            "capability_mapping_id": None,
            "source_ref": ref,
            "source_type": "SOLUTION_APPROACH",
            "source_label": "Accepted Cloud Inventory approach",
            "source_statement": solution.text,
        }
    raise HTTPException(400, "Select an operational observation, approved capability mapping, accepted approach, or metric as the benefit basis.")


def _object_storage_or_503(settings: Settings) -> ObjectStorage:
    try:
        return ObjectStorage(settings)
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return str(value)


def _model_dict(instance: Any) -> dict[str, Any]:
    return {column.name: _json_value(getattr(instance, column.name)) for column in instance.__table__.columns}


def _delete_file_objects(db: Session, storage: ObjectStorage, stmt) -> int:
    files = list(db.scalars(stmt).all())
    for file_obj in files:
        try:
            storage.delete(file_obj.storage_key)
        except FileNotFoundError:
            pass
        db.delete(file_obj)
    return len(files)


def _report_member_user_ids(db: Session, report: Report) -> set[str]:
    ids = set(db.scalars(select(ReportMember.user_id).where(ReportMember.report_id == report.id)).all())
    ids.add(report.owner_id)
    return ids



def _resolve_mapping_source(
    db: Session,
    report: Report,
    *,
    section_id: str | None,
    source_ref: str | None,
    finding_id: str | None = None,
) -> dict[str, Any]:
    """Resolve a finding or general note into a stable capability-mapping source."""
    if finding_id:
        finding = db.get(Finding, finding_id)
        if not finding or finding.report_id != report.id:
            raise HTTPException(400, "Invalid finding for this report.")
        return {
            "section_id": finding.section_id,
            "finding_id": finding.id,
            "source_ref": f"finding:{finding.id}",
            "source_type": "FINDING",
            "source_label": finding.finding_type.replace("_", " ").title(),
            "source_statement": finding.statement,
        }

    ref = (source_ref or "").strip()
    if not ref:
        raise HTTPException(400, "A finding or operational observation source is required.")

    if ref.startswith("finding:"):
        return _resolve_mapping_source(db, report, section_id=section_id, source_ref=None, finding_id=ref.split(":", 1)[1])

    if ref == "section:narrative":
        if not section_id:
            raise HTTPException(400, "Section is required for a general-note mapping.")
        section = _get_section(db, section_id)
        if section.report_id != report.id:
            raise HTTPException(400, "Section does not belong to report.")
        statement = section.narrative.strip()
        if not statement:
            raise HTTPException(400, "The section current-operations narrative is empty.")
        return {
            "section_id": section.id,
            "finding_id": None,
            "source_ref": ref,
            "source_type": "GENERAL_OBSERVATION",
            "source_label": "Observation — Current operations narrative",
            "source_statement": statement,
        }

    if ref.startswith("response:"):
        response = db.get(Response, ref.split(":", 1)[1])
        if not response or response.report_id != report.id:
            raise HTTPException(400, "Guided response is not available in this report.")
        if section_id and response.section_id != section_id:
            raise HTTPException(400, "Guided response does not belong to the selected section.")
        prompt = db.get(PromptDefinition, response.prompt_id)
        statement = response.narrative.strip() or (json.dumps(response.payload, ensure_ascii=False) if response.payload else "")
        if not statement:
            raise HTTPException(400, "The selected guided response is empty.")
        return {
            "section_id": response.section_id,
            "finding_id": None,
            "source_ref": ref,
            "source_type": "GENERAL_OBSERVATION",
            "source_label": f"Observation — {prompt.question if prompt else 'Guided response'}",
            "source_statement": statement,
        }

    raise HTTPException(400, "Unsupported operational observation source.")


def _knowledge_chunks(text: str, *, max_chars: int = 4200, max_chunks: int = 40) -> list[str]:
    paragraphs = [item.strip() for item in text.replace("\r\n", "\n").split("\n\n") if item.strip()]
    if not paragraphs:
        paragraphs = [item.strip() for item in text.split("\n") if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            slices = [paragraph[index:index + max_chars] for index in range(0, len(paragraph), max_chars)]
        else:
            slices = [paragraph]
        for piece in slices:
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
            if len(chunks) >= max_chunks:
                break
        if len(chunks) >= max_chunks:
            break
    if current and len(chunks) < max_chunks:
        chunks.append(current)
    return chunks


def _create_knowledge_candidates(db: Session, report: Report, actor: User) -> int:
    """Capture approved report knowledge without making it cross-prospect reusable.

    The admin knowledge-review workflow is the only way to de-identify and promote a candidate
    for use across prospects. This prevents accidental leakage of customer-confidential content.
    """
    created = 0
    mappings = db.execute(
        select(CapabilityMapping, Capability)
        .join(Capability, CapabilityMapping.capability_id == Capability.id)
        .where(CapabilityMapping.report_id == report.id, CapabilityMapping.approval_state == "APPROVED")
    ).all()
    for mapping, capability in mappings:
        source_ref = f"report:{report.id}:mapping:{mapping.id}"
        if db.scalar(select(KnowledgeEntry.id).where(KnowledgeEntry.source_ref == source_ref)):
            continue
        impact = None
        if mapping.finding_id:
            finding = db.get(Finding, mapping.finding_id)
            impact = finding.impact if finding else None
        content = (
            f"Observed source ({mapping.source_label or mapping.source_type}): {mapping.source_statement or 'Not stated'}\n"
            f"Impact: {impact or 'Not stated'}\n"
            f"Approved capability: {capability.name} ({capability.capability_code})\n"
            f"Approved rationale: {mapping.rationale}\n"
            f"Prerequisites: {mapping.prerequisites or capability.typical_prerequisites or 'Not stated'}"
        )
        db.add(KnowledgeEntry(
            source_type="FINAL_REPORT_MAPPING", source_ref=source_ref,
            title=f"{capability.name} — {report.title}", process_module=capability.domain,
            content=content, capability_id=capability.id, prospect_id=report.prospect_id,
            classification="CONFIDENTIAL", reusable_across_prospects=False,
            approval_state="PENDING", created_by=actor.id,
        ))
        created += 1
    benefits = list(db.scalars(select(Benefit).where(Benefit.report_id == report.id, Benefit.approval_state == "APPROVED")).all())
    for benefit in benefits:
        source_ref = f"report:{report.id}:benefit:{benefit.id}"
        if db.scalar(select(KnowledgeEntry.id).where(KnowledgeEntry.source_ref == source_ref)):
            continue
        db.add(KnowledgeEntry(
            source_type="FINAL_REPORT_BENEFIT", source_ref=source_ref,
            title=f"Approved benefit — {report.title}", content=benefit.statement,
            prospect_id=report.prospect_id, classification="CONFIDENTIAL",
            reusable_across_prospects=False, approval_state="PENDING", created_by=actor.id,
        ))
        created += 1
    return created


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: FastAPIResponse, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user = authenticate(db, payload.username, payload.password)
    if not user:
        audit(db, actor=None, action="AUTH_LOGIN_FAILED", target_type="USER", metadata={"username": payload.username})
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token, csrf = create_session(db, user, request, settings)
    set_session_cookie(response, token, settings)
    audit(db, actor=user, action="AUTH_LOGIN", target_type="USER", target_id=user.id)
    db.commit()
    return _user_payload(db, user, csrf)


@router.get("/auth/me")
def me(session=Depends(get_current_session), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_payload(db, user, session.csrf_token)


@router.post("/auth/change-password", dependencies=[Depends(require_csrf)])
def change_password(payload: PasswordChangeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if verify_password(user.password_hash, payload.new_password):
        raise HTTPException(status_code=400, detail="New password must be different.")
    user.password_hash = hash_password(payload.new_password)
    user.force_password_change = False
    audit(db, actor=user, action="AUTH_PASSWORD_CHANGED", target_type="USER", target_id=user.id)
    db.commit()
    return {"ok": True}


@router.post("/auth/logout", dependencies=[Depends(require_csrf)])
def logout(response: FastAPIResponse, session=Depends(get_current_session), user: User = Depends(get_current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    logout_session(db, session)
    clear_session_cookie(response, settings)
    audit(db, actor=user, action="AUTH_LOGOUT", target_type="USER", target_id=user.id)
    db.commit()
    return {"ok": True}


@router.get("/users")
def list_users(user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    # Collaboration selectors expose active identities only. Inactive accounts remain
    # visible to administrators through /admin/users but cannot be assigned new work.
    users = list(db.scalars(select(User).where(User.status == "ACTIVE").order_by(User.display_name, User.username)).all())
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "email": u.email, "status": u.status, "roles": sorted(user_roles(db, u.id))} for u in users]


@router.get("/admin/users")
def list_admin_users(actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    users = list(db.scalars(select(User).order_by(User.display_name, User.username)).all())
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "email": u.email, "status": u.status, "roles": sorted(user_roles(db, u.id)), "force_password_change": u.force_password_change, "last_login_at": _iso(u.last_login_at)} for u in users]


@router.post("/admin/users", dependencies=[Depends(require_csrf)])
def create_user(
    payload: UserCreate,
    actor: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    username_key = normalize_username(payload.username)
    if db.scalar(select(User).where(or_(User.username_key == username_key, User.email == str(payload.email)))):
        raise HTTPException(status_code=409, detail="Username or email already exists.")
    temporary_password = payload.password or settings.default_user_temp_password
    if not temporary_password:
        raise HTTPException(503, "The default temporary user password is not configured.")
    if len(temporary_password) < 10:
        raise HTTPException(500, "The configured temporary password does not meet the 10-character minimum.")
    groups = [
        any(c.islower() for c in temporary_password),
        any(c.isupper() for c in temporary_password),
        any(c.isdigit() for c in temporary_password),
        any(not c.isalnum() for c in temporary_password),
    ]
    if sum(groups) < 3:
        raise HTTPException(500, "The configured temporary password does not meet password complexity requirements.")
    new_user = User(
        username=payload.username,
        username_key=username_key,
        email=str(payload.email),
        display_name=payload.display_name,
        password_hash=hash_password(temporary_password),
        status="ACTIVE",
        force_password_change=True,
    )
    db.add(new_user)
    db.flush()
    for role in set(payload.roles):
        db.add(UserRole(user_id=new_user.id, role=role.upper()))
    audit(db, actor=actor, action="USER_CREATED", target_type="USER", target_id=new_user.id, metadata={"roles": payload.roles, "temporary_password_source": "CUSTOM" if payload.password else "CONFIGURED_DEFAULT"})
    db.commit()
    return _user_payload(db, new_user)


@router.put("/admin/users/{user_id}/roles", dependencies=[Depends(require_csrf)])
def admin_update_user_roles(
    user_id: str,
    payload: AdminUserRolesUpdate,
    actor: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    new_roles = {role.upper() for role in payload.roles}
    old_roles = user_roles(db, target.id)
    if target.id == actor.id and "ADMIN" not in new_roles:
        raise HTTPException(400, "You cannot remove the Administrator role from your own account.")
    if "ADMIN" in old_roles and "ADMIN" not in new_roles and target.status == "ACTIVE":
        active_admin_count = db.scalar(
            select(func.count())
            .select_from(UserRole)
            .join(User, User.id == UserRole.user_id)
            .where(UserRole.role == "ADMIN", User.status == "ACTIVE")
        ) or 0
        if active_admin_count <= 1:
            raise HTTPException(409, "The last active administrator must retain the Administrator role.")
    if "OWNER" in old_roles and "OWNER" not in new_roles:
        owns_reports = bool(db.scalar(select(Report.id).where(Report.owner_id == target.id).limit(1)))
        owns_engagements = bool(db.scalar(select(Engagement.id).where(Engagement.owner_id == target.id).limit(1)))
        if owns_reports or owns_engagements:
            raise HTTPException(409, "This user still owns reports or engagements. Reassign owned work before removing the Owner role.")
    db.execute(delete(UserRole).where(UserRole.user_id == target.id))
    for role in sorted(new_roles):
        db.add(UserRole(user_id=target.id, role=role))
    audit(db, actor=actor, action="USER_ROLES_UPDATED", target_type="USER", target_id=target.id, metadata={"old_roles": sorted(old_roles), "new_roles": sorted(new_roles)})
    db.commit()
    return {"ok": True, "roles": sorted(new_roles)}


@router.post("/admin/users/{user_id}/reset-password", dependencies=[Depends(require_csrf)])
def admin_reset_user_password(
    user_id: str,
    actor: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    if target.id == actor.id:
        raise HTTPException(400, "Use Change password for your own account.")
    temporary_password = settings.default_user_temp_password
    if not temporary_password:
        raise HTTPException(503, "The default temporary user password is not configured.")
    if len(temporary_password) < 10:
        raise HTTPException(500, "The configured temporary password does not meet the 10-character minimum.")
    groups = [
        any(c.islower() for c in temporary_password),
        any(c.isupper() for c in temporary_password),
        any(c.isdigit() for c in temporary_password),
        any(not c.isalnum() for c in temporary_password),
    ]
    if sum(groups) < 3:
        raise HTTPException(500, "The configured temporary password does not meet password complexity requirements.")
    target.password_hash = hash_password(temporary_password)
    target.force_password_change = True
    target.failed_login_count = 0
    target.locked_until = None
    db.execute(delete(UserSession).where(UserSession.user_id == target.id))
    audit(db, actor=actor, action="USER_PASSWORD_RESET", target_type="USER", target_id=target.id, metadata={"sessions_revoked": True, "force_password_change": True, "status": target.status})
    db.commit()
    return {"ok": True, "force_password_change": True, "status": target.status}


@router.patch("/admin/users/{user_id}/status", dependencies=[Depends(require_csrf)])
def admin_update_user_status(
    user_id: str,
    payload: AdminUserStatusUpdate,
    actor: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    requested_status = payload.status.upper()
    if target.status == requested_status:
        return {"ok": True, "status": target.status, "replacement_user_id": None}

    if requested_status == "ACTIVE":
        roles = user_roles(db, target.id)
        if not roles:
            raise HTTPException(409, "Assign at least one role before activating this user.")
        target.status = "ACTIVE"
        target.failed_login_count = 0
        target.locked_until = None
        audit(db, actor=actor, action="USER_ACTIVATED", target_type="USER", target_id=target.id, metadata={"roles": sorted(roles)})
        db.commit()
        return {"ok": True, "status": "ACTIVE", "replacement_user_id": None}

    if target.id == actor.id:
        raise HTTPException(400, "You cannot deactivate your own administrator account.")
    target_roles = user_roles(db, target.id)
    if "ADMIN" in target_roles:
        active_admin_count = db.scalar(
            select(func.count())
            .select_from(UserRole)
            .join(User, User.id == UserRole.user_id)
            .where(UserRole.role == "ADMIN", User.status == "ACTIVE")
        ) or 0
        if active_admin_count <= 1:
            raise HTTPException(409, "The last active administrator cannot be deactivated.")

    owned_reports = list(db.scalars(select(Report).where(Report.owner_id == target.id)).all())
    owned_engagements = list(db.scalars(select(Engagement).where(Engagement.owner_id == target.id)).all())
    replacement = None
    if owned_reports or owned_engagements:
        if not payload.replacement_user_id:
            raise HTTPException(409, "This user owns reports or engagements. Select an active replacement owner before deactivating the user.")
        replacement = db.get(User, payload.replacement_user_id)
        if not replacement or replacement.status != "ACTIVE" or replacement.id == target.id:
            raise HTTPException(400, "Replacement owner must be another active user.")
        if not user_roles(db, replacement.id).intersection({"OWNER", "ADMIN"}):
            raise HTTPException(400, "Replacement owner must have the Owner or Administrator role.")
        affected_prospect_ids = {item.prospect_id for item in owned_reports} | {item.prospect_id for item in owned_engagements}
        for prospect_id in affected_prospect_ids:
            membership = db.get(ProspectMembership, {"prospect_id": prospect_id, "user_id": replacement.id})
            if membership is None:
                db.add(ProspectMembership(prospect_id=prospect_id, user_id=replacement.id, role_scope="OWNER", created_by=actor.id))
            elif membership.role_scope != "OWNER":
                membership.role_scope = "OWNER"
        db.execute(update(Report).where(Report.owner_id == target.id).values(owner_id=replacement.id))
        db.execute(update(Engagement).where(Engagement.owner_id == target.id).values(owner_id=replacement.id))

    if replacement is not None:
        db.execute(update(ReportSection).where(ReportSection.assigned_to_user_id == target.id).values(assigned_to_user_id=replacement.id))
    else:
        db.execute(update(ReportSection).where(ReportSection.assigned_to_user_id == target.id).values(assigned_to_user_id=None))

    db.execute(delete(UserSession).where(UserSession.user_id == target.id))
    target.status = "INACTIVE"
    target.failed_login_count = 0
    target.locked_until = None
    audit(
        db, actor=actor, action="USER_DEACTIVATED", target_type="USER", target_id=target.id,
        metadata={
            "sessions_revoked": True,
            "roles_preserved": sorted(target_roles),
            "memberships_preserved": True,
            "replacement_user_id": replacement.id if replacement else None,
            "reassigned_reports": len(owned_reports),
            "reassigned_engagements": len(owned_engagements),
        },
    )
    db.commit()
    return {"ok": True, "status": "INACTIVE", "replacement_user_id": replacement.id if replacement else None}


@router.get("/prospects")
def list_prospects(user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    ids = accessible_prospect_ids(db, user)
    stmt = select(Prospect).where(Prospect.status != "DELETED").order_by(Prospect.updated_at.desc())
    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(Prospect.id.in_(ids))
    prospects = list(db.scalars(stmt).all())
    return [{"id": p.id, "name": p.name, "industry": p.industry, "opportunity": p.opportunity, "status": p.status, "retention_due_at": _iso(p.retention_due_at), "archive_prompted_at": _iso(p.archive_prompted_at), "last_exported_at": _iso(p.last_exported_at), "legal_hold": p.legal_hold, "logo_url": f"/api/prospects/{p.id}/logo" if p.logo_storage_key else None, "updated_at": _iso(p.updated_at)} for p in prospects]


@router.post("/prospects", dependencies=[Depends(require_csrf)])
def create_prospect(payload: ProspectCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    prospect = Prospect(name=payload.name, industry=payload.industry, opportunity=payload.opportunity, retention_due_at=utcnow() + timedelta(days=settings.default_retention_days), created_by=user.id)
    db.add(prospect)
    db.flush()
    db.add(ProspectMembership(prospect_id=prospect.id, user_id=user.id, role_scope="OWNER", created_by=user.id))
    audit(db, actor=user, action="PROSPECT_CREATED", target_type="PROSPECT", target_id=prospect.id, prospect_id=prospect.id)
    db.commit()
    return {"id": prospect.id, "name": prospect.name}


@router.post("/prospects/onboard", dependencies=[Depends(require_csrf)])
def onboard_prospect(
    payload: ProspectOnboardingCreate,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    prospect = Prospect(
        name=payload.prospect.name,
        industry=payload.prospect.industry,
        opportunity=payload.prospect.opportunity,
        retention_due_at=utcnow() + timedelta(days=settings.default_retention_days),
        created_by=user.id,
    )
    db.add(prospect)
    db.flush()
    db.add(ProspectMembership(prospect_id=prospect.id, user_id=user.id, role_scope="OWNER", created_by=user.id))
    audit(db, actor=user, action="PROSPECT_CREATED", target_type="PROSPECT", target_id=prospect.id, prospect_id=prospect.id, metadata={"creation_flow": "GUIDED_ONBOARDING"})

    site = None
    if payload.site:
        site = Site(
            prospect_id=prospect.id,
            name=payload.site.name,
            address=payload.site.address,
            timezone=payload.site.timezone,
            created_by=user.id,
        )
        db.add(site)
        db.flush()
        audit(db, actor=user, action="SITE_CREATED", target_type="SITE", target_id=site.id, prospect_id=prospect.id, metadata={"creation_flow": "GUIDED_ONBOARDING"})

    engagement = None
    if payload.engagement:
        engagement = Engagement(
            prospect_id=prospect.id,
            site_id=site.id if site else None,
            name=payload.engagement.name,
            survey_date=payload.engagement.survey_date,
            objectives=payload.engagement.objectives,
            owner_id=user.id,
        )
        db.add(engagement)
        db.flush()
        db.add(EngagementMember(engagement_id=engagement.id, user_id=user.id, role_scope="OWNER"))
        audit(db, actor=user, action="ENGAGEMENT_CREATED", target_type="ENGAGEMENT", target_id=engagement.id, prospect_id=prospect.id, metadata={"creation_flow": "GUIDED_ONBOARDING", "site_id": site.id if site else None})

    db.commit()
    next_tab = "reports" if engagement else "engagements" if site else "sites"
    return {
        "id": prospect.id,
        "name": prospect.name,
        "site_id": site.id if site else None,
        "engagement_id": engagement.id if engagement else None,
        "next_tab": next_tab,
    }


@router.get("/prospects/{prospect_id}")
def get_prospect(prospect_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    prospect = db.get(Prospect, prospect_id)
    if not prospect:
        raise HTTPException(404, "Prospect not found.")
    scope = require_prospect_access(db, user, prospect_id)
    sites = list(db.scalars(select(Site).where(Site.prospect_id == prospect_id).order_by(Site.name)).all())
    engagements = list(db.scalars(select(Engagement).where(Engagement.prospect_id == prospect_id).order_by(Engagement.created_at.desc())).all())
    reports = list(db.scalars(select(Report).where(Report.prospect_id == prospect_id, Report.state != "DELETED").order_by(Report.updated_at.desc())).all())
    members = db.execute(select(ProspectMembership, User).join(User, ProspectMembership.user_id == User.id).where(ProspectMembership.prospect_id == prospect_id)).all()
    return {
        "prospect": {"id": prospect.id, "name": prospect.name, "industry": prospect.industry, "opportunity": prospect.opportunity, "status": prospect.status, "retention_due_at": _iso(prospect.retention_due_at), "archive_prompted_at": _iso(prospect.archive_prompted_at), "last_exported_at": _iso(prospect.last_exported_at), "legal_hold": prospect.legal_hold, "logo_url": f"/api/prospects/{prospect.id}/logo" if prospect.logo_storage_key else None},
        "access_scope": scope,
        "sites": [{"id": s.id, "name": s.name, "address": s.address, "timezone": s.timezone} for s in sites],
        "engagements": [{"id": e.id, "name": e.name, "site_id": e.site_id, "survey_date": _iso(e.survey_date), "status": e.status, "owner_id": e.owner_id} for e in engagements],
        "reports": [{"id": r.id, "title": r.title, "state": r.state, "report_kind": r.report_kind, "owner_id": r.owner_id, "revision": r.revision, "updated_at": _iso(r.updated_at), "merged_into_report_id": r.merged_into_report_id} for r in reports],
        "members": [{"user_id": u.id, "display_name": u.display_name or u.username, "email": u.email, "role_scope": m.role_scope} for m, u in members],
    }


@router.get("/prospects/{prospect_id}/logo")
def get_prospect_logo(
    prospect_id: str,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    prospect = db.get(Prospect, prospect_id)
    if not prospect:
        raise HTTPException(404, "Prospect not found.")
    require_prospect_access(db, user, prospect_id)
    if not prospect.logo_storage_key:
        raise HTTPException(404, "Prospect logo not found.")
    try:
        storage = _object_storage_or_503(settings)
        data = storage.get_bytes(prospect.logo_storage_key)
    except FileNotFoundError:
        raise HTTPException(404, "Prospect logo not found.")
    except Exception:
        raise HTTPException(503, "Prospect logo storage is not configured for this environment.")
    return StreamingResponse(io.BytesIO(data), media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.post("/prospects/{prospect_id}/logo", dependencies=[Depends(require_csrf)])
async def upload_prospect_logo(
    prospect_id: str,
    file: UploadFile = File(...),
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    prospect = db.get(Prospect, prospect_id)
    if not prospect:
        raise HTTPException(404, "Prospect not found.")
    require_prospect_access(db, user, prospect_id, "OWNER")
    data = await file.read(min(settings.max_upload_bytes, 10_485_760) + 1)
    if len(data) > min(settings.max_upload_bytes, 10_485_760):
        raise HTTPException(413, "Prospect logo exceeds the 10 MB limit.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1600, 800), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            logo_bytes = output.getvalue()
    except Exception:
        raise HTTPException(400, "The uploaded prospect logo could not be decoded as an image.")

    old_key = prospect.logo_storage_key
    key = build_storage_key(prospect.id, "branding", uuid.uuid4().hex, "prospect-logo.png")
    try:
        storage = _object_storage_or_503(settings)
        stored = storage.put_bytes(key, logo_bytes, "image/png")
    except Exception:
        raise HTTPException(503, "Prospect logo storage is not configured for this environment.")

    prospect.logo_storage_key = stored.key
    audit(db, actor=user, action="PROSPECT_LOGO_UPDATED", target_type="PROSPECT", target_id=prospect.id, prospect_id=prospect.id)
    db.commit()
    if old_key:
        try:
            storage.delete(old_key)
        except Exception:
            pass
    return {"ok": True, "logo_url": f"/api/prospects/{prospect.id}/logo"}


@router.get("/prospects/{prospect_id}/export")
def export_prospect(prospect_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    prospect = db.get(Prospect, prospect_id)
    if not prospect:
        raise HTTPException(404, "Prospect not found.")
    require_prospect_access(db, user, prospect_id, "OWNER")
    storage = _object_storage_or_503(settings)
    reports = list(db.scalars(select(Report).where(Report.prospect_id == prospect_id)).all())
    report_ids = [report.id for report in reports]
    engagements = list(db.scalars(select(Engagement).where(Engagement.prospect_id == prospect_id)).all())
    engagement_ids = [item.id for item in engagements]
    evidence = list(db.scalars(select(EvidenceItem).where(EvidenceItem.prospect_id == prospect_id)).all())
    file_objects = list(db.scalars(select(FileObject).where(FileObject.prospect_id == prospect_id)).all())
    mappings = list(db.scalars(select(CapabilityMapping).where(CapabilityMapping.report_id.in_(report_ids))).all()) if report_ids else []
    capability_ids = {mapping.capability_id for mapping in mappings}
    capability_ids.update(db.scalars(select(KnowledgeEntry.capability_id).where(KnowledgeEntry.prospect_id == prospect_id, KnowledgeEntry.capability_id.is_not(None))).all())
    tables: dict[str, list[Any]] = {
        "prospect": [prospect],
        "prospect_memberships": list(db.scalars(select(ProspectMembership).where(ProspectMembership.prospect_id == prospect_id)).all()),
        "sites": list(db.scalars(select(Site).where(Site.prospect_id == prospect_id)).all()),
        "engagements": engagements,
        "engagement_members": list(db.scalars(select(EngagementMember).where(EngagementMember.engagement_id.in_(engagement_ids))).all()) if engagement_ids else [],
        "reports": reports,
        "report_members": list(db.scalars(select(ReportMember).where(ReportMember.report_id.in_(report_ids))).all()) if report_ids else [],
        "report_sections": list(db.scalars(select(ReportSection).where(ReportSection.report_id.in_(report_ids))).all()) if report_ids else [],
        "responses": list(db.scalars(select(Response).where(Response.report_id.in_(report_ids))).all()) if report_ids else [],
        "findings": list(db.scalars(select(Finding).where(Finding.report_id.in_(report_ids))).all()) if report_ids else [],
        "metrics": list(db.scalars(select(Metric).where(Metric.report_id.in_(report_ids))).all()) if report_ids else [],
        "evidence_items": evidence,
        "file_objects": file_objects,
        "capability_mappings": mappings,
        "benefits": list(db.scalars(select(Benefit).where(Benefit.report_id.in_(report_ids))).all()) if report_ids else [],
        "ai_jobs": list(db.scalars(select(AiJob).where(AiJob.report_id.in_(report_ids))).all()) if report_ids else [],
        "ai_suggestions": list(db.scalars(select(AiSuggestion).where(AiSuggestion.report_id.in_(report_ids))).all()) if report_ids else [],
        "comments": list(db.scalars(select(Comment).where(Comment.report_id.in_(report_ids))).all()) if report_ids else [],
        "approvals": list(db.scalars(select(Approval).where(Approval.report_id.in_(report_ids))).all()) if report_ids else [],
        "merge_operations": list(db.scalars(select(MergeOperation).where(MergeOperation.target_report_id.in_(report_ids))).all()) if report_ids else [],
        "validation_runs": list(db.scalars(select(ValidationRun).where(ValidationRun.report_id.in_(report_ids))).all()) if report_ids else [],
        "publications": list(db.scalars(select(Publication).where(Publication.report_id.in_(report_ids))).all()) if report_ids else [],
        "knowledge_entries": list(db.scalars(select(KnowledgeEntry).where(KnowledgeEntry.prospect_id == prospect_id)).all()),
        "audit_events": list(db.scalars(select(AuditEvent).where(AuditEvent.prospect_id == prospect_id).order_by(AuditEvent.created_at)).all()),
        "capabilities_referenced": list(db.scalars(select(Capability).where(Capability.id.in_(capability_ids))).all()) if capability_ids else [],
    }
    merge_ids = [item.id for item in tables["merge_operations"]]
    tables["merge_lineage"] = list(db.scalars(select(MergeLineage).where(MergeLineage.merge_operation_id.in_(merge_ids))).all()) if merge_ids else []
    user_ids: set[str] = set()
    for membership in tables["prospect_memberships"] + tables["report_members"] + tables["engagement_members"]:
        user_ids.add(membership.user_id)
    for report in reports:
        user_ids.add(report.owner_id)
    safe_users = list(db.scalars(select(User).where(User.id.in_(user_ids))).all()) if user_ids else []

    export_stamp = utcnow()
    fd, temp_path = tempfile.mkstemp(prefix=f"ci-discovery-{prospect_id}-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            manifest = {
                "schema_version": 1,
                "exported_at": _iso(export_stamp),
                "exported_by": {"id": user.id, "username": user.username},
                "prospect_id": prospect.id,
                "prospect_name": prospect.name,
                "file_count": len(file_objects),
                "record_counts": {name: len(items) for name, items in tables.items()},
            }
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            for name, items in tables.items():
                archive.writestr(f"data/{name}.json", json.dumps([_model_dict(item) for item in items], indent=2, ensure_ascii=False))
            archive.writestr("data/users.json", json.dumps([{"id": item.id, "username": item.username, "email": item.email, "display_name": item.display_name, "status": item.status} for item in safe_users], indent=2, ensure_ascii=False))
            used_names: set[str] = set()
            for file_obj in file_objects:
                base_name = safe_filename(file_obj.file_name)
                archive_name = f"files/{file_obj.id}-{base_name}"
                if archive_name in used_names:
                    archive_name = f"files/{file_obj.id}-{uuid.uuid4().hex[:8]}-{base_name}"
                used_names.add(archive_name)
                try:
                    archive.writestr(archive_name, storage.get_bytes(file_obj.storage_key))
                except FileNotFoundError:
                    archive.writestr(f"missing-files/{file_obj.id}.json", json.dumps({"storage_key": file_obj.storage_key, "file_name": file_obj.file_name, "reason": "Object not found"}, indent=2))
        prospect.last_exported_at = export_stamp
        audit(db, actor=user, action="PROSPECT_EXPORTED", target_type="PROSPECT", target_id=prospect.id, prospect_id=prospect.id, metadata={"records": manifest["record_counts"], "files": len(file_objects)})
        db.commit()
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise
    download_name = f"{safe_filename(prospect.name)}-discovery-export-{export_stamp.date().isoformat()}.zip"
    return FileResponse(temp_path, media_type="application/zip", filename=download_name, background=BackgroundTask(lambda: Path(temp_path).unlink(missing_ok=True)))


@router.post("/prospects/{prospect_id}/archive", dependencies=[Depends(require_csrf)])
def archive_prospect(prospect_id: str, payload: ProspectArchiveRequest, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    prospect = db.get(Prospect, prospect_id)
    if not prospect:
        raise HTTPException(404, "Prospect not found.")
    require_prospect_access(db, user, prospect_id, "OWNER")
    if prospect.legal_hold:
        raise HTTPException(409, "Prospect is under legal hold and cannot be archived.")
    prospect.status = "ARCHIVED"
    audit(db, actor=user, action="PROSPECT_ARCHIVED", target_type="PROSPECT", target_id=prospect.id, prospect_id=prospect.id, metadata={"reason": payload.reason})
    db.commit()
    return {"ok": True, "status": prospect.status}


@router.get("/admin/retention-due")
def retention_due(days: int = 30, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    cutoff = utcnow() + timedelta(days=max(0, min(days, 365)))
    items = list(db.scalars(select(Prospect).where(Prospect.status.in_(["ACTIVE", "RETENTION_REVIEW", "ARCHIVED"]), Prospect.retention_due_at <= cutoff).order_by(Prospect.retention_due_at)).all())
    return [{"id": item.id, "name": item.name, "status": item.status, "retention_due_at": _iso(item.retention_due_at), "last_exported_at": _iso(item.last_exported_at), "legal_hold": item.legal_hold} for item in items]


@router.delete("/admin/prospects/{prospect_id}", dependencies=[Depends(require_csrf)])
def permanently_delete_prospect(prospect_id: str, payload: ProspectDeleteRequest, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    prospect = db.get(Prospect, prospect_id)
    if not prospect:
        raise HTTPException(404, "Prospect not found.")
    if payload.confirm_name.strip() != prospect.name:
        raise HTTPException(400, "Prospect name confirmation does not match.")
    if prospect.legal_hold:
        raise HTTPException(409, "Prospect is under legal hold and cannot be deleted.")
    if not payload.confirm_exported or not prospect.last_exported_at:
        raise HTTPException(409, "A completed prospect export and explicit export confirmation are required before permanent deletion.")
    storage = _object_storage_or_503(settings)
    files = list(db.scalars(select(FileObject).where(FileObject.prospect_id == prospect.id)).all())
    for file_obj in files:
        try:
            storage.delete(file_obj.storage_key)
        except FileNotFoundError:
            pass
    audit(db, actor=actor, action="PROSPECT_PERMANENT_DELETE", target_type="PROSPECT", target_id=prospect.id, metadata={"name": prospect.name, "files_deleted": len(files), "last_exported_at": _iso(prospect.last_exported_at)})
    db.delete(prospect)
    db.commit()
    return {"ok": True, "deleted_prospect_id": prospect_id, "files_deleted": len(files)}


@router.post("/prospects/{prospect_id}/members", dependencies=[Depends(require_csrf)])
def add_prospect_member(prospect_id: str, user_id: str = Form(...), role_scope: str = Form("CONTRIBUTOR"), actor: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    require_prospect_access(db, actor, prospect_id, "OWNER")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    membership = db.get(ProspectMembership, (prospect_id, user_id))
    if membership:
        membership.role_scope = role_scope.upper()
    else:
        db.add(ProspectMembership(prospect_id=prospect_id, user_id=user_id, role_scope=role_scope.upper(), created_by=actor.id))
    audit(db, actor=actor, action="PROSPECT_MEMBER_UPSERTED", target_type="PROSPECT_MEMBERSHIP", target_id=user_id, prospect_id=prospect_id, metadata={"role_scope": role_scope.upper()})
    db.commit()
    return {"ok": True}


@router.post("/prospects/{prospect_id}/sites", dependencies=[Depends(require_csrf)])
def create_site(prospect_id: str, payload: SiteCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    require_prospect_access(db, user, prospect_id)
    site = Site(prospect_id=prospect_id, name=payload.name, address=payload.address, timezone=payload.timezone, created_by=user.id)
    db.add(site)
    audit(db, actor=user, action="SITE_CREATED", target_type="SITE", target_id=site.id, prospect_id=prospect_id)
    db.commit()
    return {"id": site.id, "name": site.name}


@router.post("/prospects/{prospect_id}/engagements", dependencies=[Depends(require_csrf)])
def create_engagement(prospect_id: str, payload: EngagementCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    require_prospect_access(db, user, prospect_id)
    if payload.site_id:
        site = db.get(Site, payload.site_id)
        if not site or site.prospect_id != prospect_id:
            raise HTTPException(400, "Site does not belong to prospect.")
    engagement = Engagement(prospect_id=prospect_id, site_id=payload.site_id, name=payload.name, survey_date=payload.survey_date, objectives=payload.objectives, owner_id=user.id)
    db.add(engagement)
    db.flush()
    db.add(EngagementMember(engagement_id=engagement.id, user_id=user.id, role_scope="OWNER"))
    audit(db, actor=user, action="ENGAGEMENT_CREATED", target_type="ENGAGEMENT", target_id=engagement.id, prospect_id=prospect_id)
    db.commit()
    return {"id": engagement.id, "name": engagement.name}


@router.get("/report-templates")
def list_templates(user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    items = list(db.scalars(select(ReportTemplate).where(ReportTemplate.status == "ACTIVE").order_by(ReportTemplate.name)).all())
    return [{"id": t.id, "name": t.name, "report_type": t.report_type, "version": t.version} for t in items]


@router.post("/prospects/{prospect_id}/reports", dependencies=[Depends(require_csrf)])
def create_report(prospect_id: str, payload: ReportCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    require_prospect_access(db, user, prospect_id)
    engagement = db.get(Engagement, payload.engagement_id)
    if not engagement or engagement.prospect_id != prospect_id:
        raise HTTPException(400, "Engagement does not belong to prospect.")
    template = db.get(ReportTemplate, payload.report_template_id) if payload.report_template_id else db.scalar(select(ReportTemplate).where(ReportTemplate.status == "ACTIVE", ReportTemplate.report_type == "FULL_DISCOVERY").order_by(ReportTemplate.version.desc()))
    if not template:
        raise HTTPException(409, "No active report template is configured.")
    report = Report(prospect_id=prospect_id, engagement_id=engagement.id, site_id=payload.site_id or engagement.site_id, report_template_id=template.id, branding_profile_id=template.branding_profile_id, owner_id=user.id, title=payload.title, report_kind=payload.report_kind)
    db.add(report)
    db.flush()
    db.add(ReportMember(report_id=report.id, user_id=user.id, role_scope="OWNER"))
    for section_template in db.scalars(select(SectionTemplate).where(SectionTemplate.report_template_id == template.id).order_by(SectionTemplate.display_order)).all():
        db.add(ReportSection(report_id=report.id, section_template_id=section_template.id, stable_key=section_template.stable_key, title=section_template.title, process_module=section_template.process_module, display_order=section_template.display_order, required_on_final=section_template.required_on_final, created_by=user.id, updated_by=user.id))
    audit(db, actor=user, action="REPORT_CREATED", target_type="REPORT", target_id=report.id, prospect_id=prospect_id)
    db.commit()
    return {"id": report.id, "title": report.title}


@router.patch("/reports/{report_id}", dependencies=[Depends(require_csrf)])
def update_report(report_id: str, payload: ReportUpdate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "REVIEWER")
    if report.state in {"MERGED", "DELETED", "FINALIZED"}:
        raise HTTPException(409, f"Report status cannot be changed while the report is {report.state.lower()}.")
    report.state = payload.state
    _increment_report(report)
    audit(db, actor=user, action="REPORT_STATUS_UPDATED", target_type="REPORT", target_id=report.id, prospect_id=report.prospect_id, metadata={"state": report.state})
    db.commit()
    return {"ok": True, "state": report.state, "revision": report.revision}


@router.get("/storage/status")
def get_storage_status(user: User = Depends(enforce_password_changed), settings: Settings = Depends(get_settings)):
    return storage_configuration_status(settings)


@router.get("/reports/{report_id}/draft.docx")
def download_draft_docx(report_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    data = generate_docx(db, report.id, settings, publication_type="FULL_DISCOVERY", is_final=False)
    data, _ = refresh_docx_fields(data, settings)
    filename = safe_filename(report.title) or "site-discovery-report"
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="{filename}-r{report.revision}-draft.docx"'})


@router.get("/reports/{report_id}/draft.pdf")
def download_draft_pdf(report_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    docx_bytes = generate_docx(db, report.id, settings, publication_type="FULL_DISCOVERY", is_final=False)
    docx_bytes, pdf_bytes = refresh_docx_fields(docx_bytes, settings, emit_pdf=True)
    if pdf_bytes is None:
        pdf_bytes = convert_docx_to_pdf(docx_bytes, settings)
    filename = safe_filename(report.title) or "site-discovery-report"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}-r{report.revision}-draft.pdf"'})


@router.get("/reports/{report_id}")
def get_report(report_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    scope = require_report_access(db, user, report)
    prospect = db.get(Prospect, report.prospect_id)
    if not prospect:
        raise HTTPException(409, "Report prospect is unavailable.")
    sections = list(db.scalars(select(ReportSection).where(ReportSection.report_id == report.id).order_by(ReportSection.display_order)).all())
    responses = db.execute(select(Response, PromptDefinition).join(PromptDefinition, Response.prompt_id == PromptDefinition.id).where(Response.report_id == report.id, PromptDefinition.active.is_(True))).all()
    response_map: dict[str, list[dict[str, Any]]] = {}
    for response, prompt in responses:
        response_map.setdefault(response.section_id, []).append({"id": response.id, "prompt_id": prompt.id, "question": prompt.question, "answer_type": prompt.answer_type, "narrative": response.narrative, "payload": response.payload, "version": response.version})
    findings = list(db.scalars(select(Finding).where(Finding.report_id == report.id, Finding.status.notin_(CURRENT_FINDING_EXCLUDED_STATUSES)).order_by(Finding.created_at)).all())
    metrics = list(db.scalars(select(Metric).where(Metric.report_id == report.id).order_by(Metric.created_at)).all())
    evidence_items = list(db.scalars(select(EvidenceItem).where(EvidenceItem.report_id == report.id).order_by(EvidenceItem.created_at)).all())
    evidence_ids = [item.id for item in evidence_items]
    evidence_files = list(db.scalars(select(FileObject).where(FileObject.evidence_id.in_(evidence_ids))).all()) if evidence_ids else []
    files_by_evidence: dict[str, dict[str, FileObject]] = {}
    for file_obj in evidence_files:
        if not file_obj.evidence_id:
            continue
        files_by_evidence.setdefault(file_obj.evidence_id, {})[file_obj.variant] = file_obj
    capabilities = db.execute(select(CapabilityMapping, Capability).join(Capability, CapabilityMapping.capability_id == Capability.id).where(CapabilityMapping.report_id == report.id)).all()
    benefits = list(db.scalars(select(Benefit).where(Benefit.report_id == report.id).order_by(Benefit.created_at)).all())
    demo_settings = db.get(DemoPlanSettings, report.id)
    demo_priorities = list(db.scalars(select(DemoSectionPriority).where(DemoSectionPriority.report_id == report.id)).all())
    demo_plan = db.scalar(
        select(DemoPlanVersion)
        .where(DemoPlanVersion.report_id == report.id, DemoPlanVersion.is_current.is_(True))
        .order_by(DemoPlanVersion.version.desc())
    )
    suggestions = list(db.scalars(select(AiSuggestion).where(AiSuggestion.report_id == report.id).order_by(AiSuggestion.created_at.desc())).all())
    solution_versions = list(
        db.scalars(
            select(SectionContentVersion).where(
                SectionContentVersion.report_id == report.id,
                SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH",
                SectionContentVersion.is_current.is_(True),
            )
        ).all()
    )
    solution_by_section = {item.section_id: item for item in solution_versions}
    executive_summary = db.scalar(
        select(ReportContentVersion)
        .where(
            ReportContentVersion.report_id == report.id,
            ReportContentVersion.content_type == "EXECUTIVE_SUMMARY",
            ReportContentVersion.is_current.is_(True),
        )
        .order_by(ReportContentVersion.version.desc())
    )
    quality_review = db.scalar(
        select(AiSuggestion)
        .where(AiSuggestion.report_id == report.id, AiSuggestion.purpose == "REPORT_QUALITY_REVIEW")
        .order_by(AiSuggestion.created_at.desc())
    )
    readiness = calculate_report_readiness(db, report)
    review_queue = calculate_review_queue(db, report)
    publications = list(
        db.scalars(
            select(Publication)
            .where(Publication.report_id == report.id, Publication.dismissed_at.is_(None))
            .order_by(Publication.created_at.desc())
        ).all()
    )
    comments = db.execute(select(Comment, User).join(User, Comment.author_id == User.id).where(Comment.report_id == report.id).order_by(Comment.created_at)).all()
    members = db.execute(select(ReportMember, User).join(User, ReportMember.user_id == User.id).where(ReportMember.report_id == report.id)).all()
    prompt_defs = list(db.scalars(select(PromptDefinition).where(PromptDefinition.active.is_(True)).order_by(PromptDefinition.process_module, PromptDefinition.display_order)).all())
    prompts_by_module: dict[str, list[dict[str, Any]]] = {}
    for p in prompt_defs:
        prompts_by_module.setdefault(p.process_module or "GENERAL", []).append({"id": p.id, "stable_key": p.stable_key, "question": p.question, "answer_type": p.answer_type, "required_on_final": p.required_on_final, "mobile_priority": p.mobile_priority})
    return {
        "report": {"id": report.id, "prospect_id": report.prospect_id, "engagement_id": report.engagement_id, "site_id": report.site_id, "title": report.title, "report_kind": report.report_kind, "state": report.state, "revision": report.revision, "owner_id": report.owner_id, "updated_at": _iso(report.updated_at)},
        "prospect": {"id": prospect.id, "name": prospect.name, "logo_url": f"/api/prospects/{prospect.id}/logo" if prospect.logo_storage_key else None},
        "access_scope": scope,
        "executive_summary": None if not executive_summary else {
            "id": executive_summary.id, "version": executive_summary.version, "text": executive_summary.text,
            "source_type": executive_summary.source_type, "source_refs": executive_summary.source_refs,
            "created_at": _iso(executive_summary.created_at),
        },
        "quality_review": None if not quality_review else {
            "id": quality_review.id, "content": quality_review.content, "source_refs": quality_review.source_refs,
            "confidence": quality_review.confidence, "review_state": quality_review.review_state,
            "created_at": _iso(quality_review.created_at),
        },
        "readiness": readiness,
        "review_queue": review_queue,
        "sections": [{
            "id": s.id, "stable_key": s.stable_key, "title": s.title, "process_module": s.process_module, "display_order": s.display_order,
            "state": s.state, "required_on_final": s.required_on_final, "removed_reason": s.removed_reason, "narrative": s.narrative,
            "version": s.version, "responses": response_map.get(s.id, []),
            "cloud_inventory_approach": None if s.id not in solution_by_section else {
                "id": solution_by_section[s.id].id,
                "version": solution_by_section[s.id].version,
                "text": solution_by_section[s.id].text,
                "source_type": solution_by_section[s.id].source_type,
                "source_refs": solution_by_section[s.id].source_refs,
                "created_at": _iso(solution_by_section[s.id].created_at),
            },
        } for s in sections],
        "prompts_by_module": prompts_by_module,
        "findings": [{"id": f.id, "section_id": f.section_id, "finding_type": f.finding_type, "statement": f.statement, "impact": f.impact, "confidence": f.confidence, "status": f.status, "source_type": f.source_type} for f in findings],
        "metrics": [{"id": m.id, "section_id": m.section_id, "name": m.name, "value_numeric": m.value_numeric, "value_text": m.value_text, "unit": m.unit, "period": m.period, "source": m.source, "confidence": m.confidence} for m in metrics],
        "evidence": [{
            "id": item.id, "section_id": item.section_id, "evidence_type": item.evidence_type,
            "caption": item.caption, "placement": item.placement, "classification": item.classification,
            "status": item.status, "extraction_state": item.extraction_state,
            "has_extracted_text": bool(item.extracted_text),
            "ai_inclusion_recommendation": item.ai_inclusion_recommendation,
            "file": None if not files_by_evidence.get(item.id, {}).get("ORIGINAL") else {
                "id": files_by_evidence[item.id]["ORIGINAL"].id,
                "file_name": files_by_evidence[item.id]["ORIGINAL"].file_name,
                "mime_type": files_by_evidence[item.id]["ORIGINAL"].mime_type,
                "size_bytes": files_by_evidence[item.id]["ORIGINAL"].size_bytes,
                "variant": files_by_evidence[item.id]["ORIGINAL"].variant,
                "width": files_by_evidence[item.id]["ORIGINAL"].width,
                "height": files_by_evidence[item.id]["ORIGINAL"].height,
            },
            "preview_file": None if not (files_by_evidence.get(item.id, {}).get("WEB") or files_by_evidence.get(item.id, {}).get("ORIGINAL")) else {
                "id": (files_by_evidence[item.id].get("WEB") or files_by_evidence[item.id]["ORIGINAL"]).id,
                "file_name": (files_by_evidence[item.id].get("WEB") or files_by_evidence[item.id]["ORIGINAL"]).file_name,
                "mime_type": (files_by_evidence[item.id].get("WEB") or files_by_evidence[item.id]["ORIGINAL"]).mime_type,
                "size_bytes": (files_by_evidence[item.id].get("WEB") or files_by_evidence[item.id]["ORIGINAL"]).size_bytes,
                "variant": (files_by_evidence[item.id].get("WEB") or files_by_evidence[item.id]["ORIGINAL"]).variant,
                "width": (files_by_evidence[item.id].get("WEB") or files_by_evidence[item.id]["ORIGINAL"]).width,
                "height": (files_by_evidence[item.id].get("WEB") or files_by_evidence[item.id]["ORIGINAL"]).height,
            },
        } for item in evidence_items],
        "capability_mappings": [{
            "id": m.id, "section_id": m.section_id, "finding_id": m.finding_id, "source_ref": m.source_ref,
            "source_type": m.source_type, "source_label": m.source_label, "source_statement": m.source_statement,
            "capability_id": c.id, "capability_code": c.capability_code, "capability_name": c.name,
            "rationale": m.rationale, "prerequisites": m.prerequisites, "approval_state": m.approval_state,
            "ai_suggestion_id": m.ai_suggestion_id,
        } for m, c in capabilities],
        "benefits": [{
            "id": b.id, "section_id": b.section_id, "finding_id": b.finding_id,
            "capability_mapping_id": b.capability_mapping_id, "source_ref": b.source_ref,
            "source_type": b.source_type, "source_label": b.source_label,
            "source_statement": b.source_statement, "statement": b.statement,
            "category": b.category, "measure_type": b.measure_type, "formula": b.formula,
            "assumptions": b.assumptions, "confidence": b.confidence,
            "approval_state": b.approval_state, "ai_suggestion_id": b.ai_suggestion_id,
        } for b in benefits],
        "demo_settings": {
            "audience": demo_settings.audience if demo_settings else "",
            "duration_minutes": demo_settings.duration_minutes if demo_settings else 45,
            "additional_priorities": demo_settings.additional_priorities if demo_settings else "",
            "version": demo_settings.version if demo_settings else None,
        },
        "demo_section_priorities": [{
            "id": item.id, "section_id": item.section_id, "priority": item.priority,
            "user_notes": item.user_notes, "constraints": item.constraints,
            "estimated_minutes": item.estimated_minutes, "version": item.version,
        } for item in demo_priorities],
        "demo_plan": None if not demo_plan else {
            "id": demo_plan.id, "version": demo_plan.version, "content": demo_plan.content,
            "source_type": demo_plan.source_type, "source_refs": demo_plan.source_refs,
            "created_at": _iso(demo_plan.created_at),
        },
        "ai_suggestions": [{
            "id": s.id, "section_id": s.section_id, "purpose": s.purpose, "content": s.content,
            "source_refs": s.source_refs, "confidence": s.confidence, "review_state": s.review_state,
            "source_fingerprint": s.source_fingerprint, "parent_suggestion_id": s.parent_suggestion_id,
            "base_ai_text": s.base_ai_text, "refinement_instruction": s.refinement_instruction,
            "superseded_by_suggestion_id": s.superseded_by_suggestion_id,
            "reviewed_at": _iso(s.reviewed_at), "created_at": _iso(s.created_at),
        } for s in suggestions],
        "publications": [
            {
                "id": p.id,
                "publication_type": p.publication_type,
                "is_final": p.is_final,
                "status": p.status,
                "report_revision": p.report_revision,
                "docx_file_id": p.docx_file_id,
                "pdf_file_id": p.pdf_file_id,
                "error": p.error,
                "created_at": _iso(p.created_at),
                "completed_at": _iso(p.completed_at),
            }
            for p in publications
        ],
        "members": [{"user_id": member.user_id, "role_scope": member.role_scope, "display_name": member_user.display_name, "username": member_user.username} for member, member_user in members],
        "comments": [{"id": comment.id, "section_id": comment.section_id, "author_id": comment.author_id, "author_name": comment_user.display_name or comment_user.username, "body": comment.body, "status": comment.status, "created_at": _iso(comment.created_at), "resolved_at": _iso(comment.resolved_at)} for comment, comment_user in comments],
    }


@router.get("/reports/{report_id}/content-versions")
def list_report_content_versions(
    report_id: str,
    content_type: str = "EXECUTIVE_SUMMARY",
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    items = list(
        db.scalars(
            select(ReportContentVersion)
            .where(ReportContentVersion.report_id == report.id, ReportContentVersion.content_type == content_type)
            .order_by(ReportContentVersion.version.desc())
        ).all()
    )
    return [{
        "id": item.id, "content_type": item.content_type, "version": item.version, "text": item.text,
        "source_type": item.source_type, "source_refs": item.source_refs, "is_current": item.is_current,
        "created_at": _iso(item.created_at),
    } for item in items]


@router.put("/reports/{report_id}/content", dependencies=[Depends(require_csrf)])
def upsert_report_content(
    report_id: str,
    payload: ReportContentUpsert,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    current = db.scalar(
        select(ReportContentVersion)
        .where(
            ReportContentVersion.report_id == report.id,
            ReportContentVersion.content_type == payload.content_type,
            ReportContentVersion.is_current.is_(True),
        )
        .order_by(ReportContentVersion.version.desc())
    )
    if payload.expected_version is not None and (not current or current.version != payload.expected_version):
        raise HTTPException(status_code=409, detail={
            "message": "Report content changed since it was loaded.",
            "current_version": current.version if current else None,
            "current_text": current.text if current else "",
        })
    text = payload.text.strip()
    if current and current.text == text:
        return {"id": current.id, "version": current.version, "report_revision": report.revision, "unchanged": True}
    if current:
        current.is_current = False
    item = ReportContentVersion(
        report_id=report.id, content_type=payload.content_type,
        version=_next_report_content_version(db, report.id, payload.content_type),
        text=text, source_type="USER", source_refs=[], is_current=True, created_by=user.id,
    )
    db.add(item)
    _increment_report(report)
    audit(db, actor=user, action="REPORT_CONTENT_UPDATED", target_type="REPORT_CONTENT", target_id=item.id, prospect_id=report.prospect_id, metadata={"content_type": payload.content_type, "version": item.version})
    db.commit()
    return {"id": item.id, "version": item.version, "report_revision": report.revision, "unchanged": False}


@router.get("/reports/{report_id}/readiness")
def get_report_readiness(report_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    return calculate_report_readiness(db, report)


@router.get("/reports/{report_id}/review-queue")
def get_report_review_queue(report_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    return calculate_review_queue(db, report)


@router.get("/reports/{report_id}/traceability")
def get_report_traceability(report_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    return calculate_traceability(db, report)


@router.get("/reports/{report_id}/sections/{section_id}/content-versions")
def list_section_content_versions(
    report_id: str,
    section_id: str,
    content_type: str = "CURRENT_OPERATIONS",
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, section_id)
    if section.report_id != report.id:
        raise HTTPException(404, "Section not found.")
    normalized_type = content_type.strip().upper()
    if normalized_type not in {"CURRENT_OPERATIONS", "CLOUD_INVENTORY_APPROACH"}:
        raise HTTPException(400, "Unsupported section content type.")
    versions = list(
        db.scalars(
            select(SectionContentVersion)
            .where(
                SectionContentVersion.report_id == report.id,
                SectionContentVersion.section_id == section.id,
                SectionContentVersion.content_type == normalized_type,
            )
            .order_by(SectionContentVersion.version.desc())
        ).all()
    )
    return [
        {
            "id": item.id,
            "version": item.version,
            "content_type": item.content_type,
            "text": item.text,
            "source_type": item.source_type,
            "source_refs": item.source_refs,
            "ai_suggestion_id": item.ai_suggestion_id,
            "is_current": item.is_current,
            "created_by": item.created_by,
            "created_at": _iso(item.created_at),
        }
        for item in versions
    ]


@router.put("/reports/{report_id}/sections/{section_id}/content", dependencies=[Depends(require_csrf)])
def upsert_section_content(
    report_id: str,
    section_id: str,
    payload: SectionContentUpsert,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, section_id)
    if section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")
    if not section.process_module:
        raise HTTPException(400, "Cloud Inventory approach content is only available for operational sections.")

    content_type = payload.content_type.strip().upper()
    current = db.scalar(
        select(SectionContentVersion)
        .where(
            SectionContentVersion.report_id == report.id,
            SectionContentVersion.section_id == section.id,
            SectionContentVersion.content_type == content_type,
            SectionContentVersion.is_current.is_(True),
        )
        .order_by(SectionContentVersion.version.desc())
    )

    current_version = current.version if current else None
    if payload.expected_version != current_version:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Cloud Inventory approach was updated by another user.",
                "current_version": current_version,
                "current_text": current.text if current else "",
            },
        )

    proposed_text = payload.text.strip()
    if current and current.text == proposed_text:
        return {
            "id": current.id,
            "version": current.version,
            "text": current.text,
            "source_type": current.source_type,
            "created_at": _iso(current.created_at),
            "section_version": section.version,
            "report_revision": report.revision,
            "unchanged": True,
        }

    for item in db.scalars(
        select(SectionContentVersion).where(
            SectionContentVersion.report_id == report.id,
            SectionContentVersion.section_id == section.id,
            SectionContentVersion.content_type == content_type,
            SectionContentVersion.is_current.is_(True),
        )
    ).all():
        item.is_current = False

    version = SectionContentVersion(
        report_id=report.id,
        section_id=section.id,
        content_type=content_type,
        version=_next_content_version(db, section.id, content_type),
        text=proposed_text,
        source_type="USER",
        source_refs=[{
            "ref": "manual:cloud-inventory-approach",
            "label": "Manual Cloud Inventory approach",
            "type": "MANUAL_ENTRY",
        }],
        is_current=True,
        created_by=user.id,
    )
    db.add(version)
    section.version += 1
    section.updated_by = user.id
    _increment_report(report)
    db.flush()
    audit(
        db,
        actor=user,
        action="SECTION_CONTENT_MANUAL_SAVED",
        target_type="SECTION_CONTENT_VERSION",
        target_id=version.id,
        prospect_id=report.prospect_id,
        metadata={
            "report_id": report.id,
            "section_id": section.id,
            "content_type": content_type,
            "version": version.version,
            "cleared": not bool(proposed_text),
        },
    )
    db.commit()
    return {
        "id": version.id,
        "version": version.version,
        "text": version.text,
        "source_type": version.source_type,
        "created_at": _iso(version.created_at),
        "section_version": section.version,
        "report_revision": report.revision,
        "unchanged": False,
    }


@router.post("/reports/{report_id}/members", dependencies=[Depends(require_csrf)])
def add_report_member(report_id: str, user_id: str = Form(...), role_scope: str = Form("CONTRIBUTOR"), actor: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, actor, report, "OWNER")
    if not db.get(User, user_id):
        raise HTTPException(404, "User not found.")
    item = db.get(ReportMember, (report.id, user_id))
    if item:
        item.role_scope = role_scope.upper()
    else:
        db.add(ReportMember(report_id=report.id, user_id=user_id, role_scope=role_scope.upper()))
    audit(db, actor=actor, action="REPORT_MEMBER_UPSERTED", target_type="REPORT_MEMBER", target_id=user_id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "role_scope": role_scope.upper()})
    db.commit()
    return {"ok": True}


@router.get("/reports/{report_id}/comments")
def list_comments(report_id: str, section_id: str | None = None, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    stmt = select(Comment, User).join(User, Comment.author_id == User.id).where(Comment.report_id == report.id)
    if section_id:
        stmt = stmt.where(Comment.section_id == section_id)
    rows = db.execute(stmt.order_by(Comment.created_at)).all()
    return [{"id": c.id, "section_id": c.section_id, "author_id": c.author_id, "author_name": u.display_name or u.username, "body": c.body, "status": c.status, "created_at": _iso(c.created_at), "resolved_at": _iso(c.resolved_at)} for c, u in rows]


@router.post("/reports/{report_id}/comments", dependencies=[Depends(require_csrf)])
def create_comment(report_id: str, payload: CommentCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    if payload.section_id:
        section = _get_section(db, payload.section_id)
        if section.report_id != report.id:
            raise HTTPException(400, "Section does not belong to report.")
    comment = Comment(report_id=report.id, section_id=payload.section_id, author_id=user.id, body=payload.body)
    db.add(comment)
    db.flush()
    audit(db, actor=user, action="COMMENT_CREATED", target_type="COMMENT", target_id=comment.id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "section_id": payload.section_id})
    db.commit()
    return {"id": comment.id, "status": comment.status}


@router.post("/reports/{report_id}/comments/{comment_id}/resolve", dependencies=[Depends(require_csrf)])
def resolve_comment(report_id: str, comment_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "REVIEWER")
    comment = db.get(Comment, comment_id)
    if not comment or comment.report_id != report.id:
        raise HTTPException(404, "Comment not found.")
    comment.status = "RESOLVED"
    comment.resolved_at = utcnow()
    audit(db, actor=user, action="COMMENT_RESOLVED", target_type="COMMENT", target_id=comment.id, prospect_id=report.prospect_id)
    db.commit()
    return {"ok": True}


@router.post("/reports/{report_id}/sections", dependencies=[Depends(require_csrf)])
def add_section(report_id: str, payload: SectionCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    max_order = db.scalar(select(func.max(ReportSection.display_order)).where(ReportSection.report_id == report.id)) or 0
    stable = f"custom-{uuid.uuid4().hex[:12]}"
    section = ReportSection(report_id=report.id, stable_key=stable, title=payload.title, process_module=payload.process_module, display_order=max_order + 10, required_on_final=False, created_by=user.id, updated_by=user.id)
    db.add(section)
    _increment_report(report)
    audit(db, actor=user, action="REPORT_SECTION_CREATED", target_type="REPORT_SECTION", target_id=section.id, prospect_id=report.prospect_id, metadata={"report_id": report.id})
    db.commit()
    return {"id": section.id, "stable_key": section.stable_key}


@router.patch("/reports/{report_id}/sections/{section_id}", dependencies=[Depends(require_csrf)])
def update_section(report_id: str, section_id: str, payload: SectionUpdate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, section_id)
    if section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")
    data = payload.model_dump(exclude_unset=True)
    expected_version = data.pop("expected_version", None)
    if expected_version is not None and expected_version != section.version:
        raise HTTPException(status_code=409, detail={"message": "Section was updated by another user.", "current_version": section.version, "current_narrative": section.narrative, "current_state": section.state})
    if data.get("state") == "REMOVED":
        require_report_access(db, user, report, "OWNER")
        if not data.get("removed_reason") and not section.removed_reason:
            raise HTTPException(400, "A removal reason is required.")
    narrative_findings = None
    for key, value in data.items():
        setattr(section, key, value)
    if "narrative" in data:
        narrative_findings = sync_narrative_findings(db, report_id=report.id, section=section, actor_user_id=user.id)
    section.version += 1
    section.updated_by = user.id
    _increment_report(report)
    audit(db, actor=user, action="REPORT_SECTION_UPDATED", target_type="REPORT_SECTION", target_id=section.id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "fields": sorted(data)})
    db.commit()
    return {
        "ok": True,
        "version": section.version,
        "report_revision": report.revision,
        "findings": None if narrative_findings is None else [
            {"id": f.id, "section_id": f.section_id, "finding_type": f.finding_type, "statement": f.statement, "impact": f.impact, "confidence": f.confidence, "status": f.status, "source_type": f.source_type}
            for f in narrative_findings
        ],
    }


@router.put("/reports/{report_id}/sections/{section_id}/responses", dependencies=[Depends(require_csrf)])
def upsert_response(report_id: str, section_id: str, payload: ResponseUpsert, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, section_id)
    prompt = db.get(PromptDefinition, payload.prompt_id)
    if section.report_id != report.id or not prompt:
        raise HTTPException(400, "Invalid section or prompt.")
    if payload.client_mutation_id:
        existing_mutation = db.scalar(select(Response).where(Response.report_id == report.id, Response.client_mutation_id == payload.client_mutation_id))
        if existing_mutation:
            return {"id": existing_mutation.id, "version": existing_mutation.version, "deduplicated": True}
    item = db.scalar(select(Response).where(Response.section_id == section.id, Response.prompt_id == prompt.id))
    if item and payload.expected_version is not None and payload.expected_version != item.version:
        raise HTTPException(status_code=409, detail={"message": "Response was updated by another user.", "current_version": item.version, "current_narrative": item.narrative, "current_payload": item.payload})
    if not item and payload.expected_version is not None:
        raise HTTPException(status_code=409, detail={"message": "Response no longer exists or has not been created.", "current_version": None})
    if item:
        item.narrative = payload.narrative
        item.payload = payload.payload
        item.version += 1
        item.authored_by = user.id
        item.client_mutation_id = payload.client_mutation_id or item.client_mutation_id
    else:
        item = Response(report_id=report.id, section_id=section.id, prompt_id=prompt.id, narrative=payload.narrative, payload=payload.payload, client_mutation_id=payload.client_mutation_id, authored_by=user.id)
        db.add(item)
    section.version += 1
    section.updated_by = user.id
    _increment_report(report)
    audit(db, actor=user, action="RESPONSE_UPSERTED", target_type="RESPONSE", target_id=item.id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "section_id": section.id, "prompt_id": prompt.id})
    db.commit()
    return {"id": item.id, "version": item.version, "report_revision": report.revision}


@router.post("/reports/{report_id}/quick-capture", dependencies=[Depends(require_csrf)])
def quick_capture(report_id: str, payload: QuickCaptureRequest, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, payload.section_id)
    if section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")
    if payload.client_mutation_id:
        existing = db.scalar(select(Finding).where(Finding.report_id == report.id, Finding.client_mutation_id == payload.client_mutation_id))
        if existing:
            return {"id": existing.id, "deduplicated": True, "version": section.version, "narrative": section.narrative}
    try:
        finding_type = normalize_finding_type(payload.finding_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    section.narrative = append_narrative_entry(
        section.narrative,
        finding_type=finding_type,
        statement=payload.note,
        impact=payload.impact,
    )
    finding = Finding(
        report_id=report.id,
        section_id=section.id,
        finding_type=finding_type,
        statement=payload.note.strip(),
        impact=payload.impact.strip() if payload.impact else None,
        confidence=payload.confidence,
        status="DRAFT",
        source_type=NARRATIVE_DERIVED_SOURCE,
        client_mutation_id=payload.client_mutation_id,
        created_by=user.id,
    )
    db.add(finding)
    db.flush()
    narrative_findings = sync_narrative_findings(db, report_id=report.id, section=section, actor_user_id=user.id)
    section.updated_by = user.id
    section.version += 1
    _increment_report(report)
    audit(
        db,
        actor=user,
        action="QUICK_CAPTURE_APPENDED_TO_NARRATIVE",
        target_type="REPORT_SECTION",
        target_id=section.id,
        prospect_id=report.prospect_id,
        metadata={"report_id": report.id, "section_id": section.id, "finding_type": finding_type, "derived_finding_id": finding.id},
    )
    db.commit()
    return {
        "id": finding.id, "version": section.version, "narrative": section.narrative, "report_revision": report.revision,
        "findings": [
            {"id": f.id, "section_id": f.section_id, "finding_type": f.finding_type, "statement": f.statement, "impact": f.impact, "confidence": f.confidence, "status": f.status, "source_type": f.source_type}
            for f in narrative_findings
        ],
    }


@router.post("/reports/{report_id}/findings", dependencies=[Depends(require_csrf)])
def create_finding(report_id: str, payload: FindingCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    """Backward-compatible typed-note endpoint.

    Section-scoped findings are now written into Current Operations Narrative and
    represented by a synchronized internal typed index. The user-facing Findings
    editing surface was retired in v0.8.9.
    """
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    try:
        finding_type = normalize_finding_type(payload.finding_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if payload.section_id:
        section = _get_section(db, payload.section_id)
        if section.report_id != report.id:
            raise HTTPException(400, "Section does not belong to report.")
        if payload.client_mutation_id:
            existing = db.scalar(select(Finding).where(Finding.report_id == report.id, Finding.client_mutation_id == payload.client_mutation_id))
            if existing:
                return {"id": existing.id, "deduplicated": True, "version": section.version, "narrative": section.narrative}
        section.narrative = append_narrative_entry(
            section.narrative, finding_type=finding_type, statement=payload.statement, impact=payload.impact
        )
        finding = Finding(
            report_id=report.id, section_id=section.id, finding_type=finding_type,
            statement=payload.statement.strip(), impact=payload.impact.strip() if payload.impact else None,
            confidence=payload.confidence, status="DRAFT", source_type=NARRATIVE_DERIVED_SOURCE,
            client_mutation_id=payload.client_mutation_id, created_by=user.id,
        )
        db.add(finding)
        db.flush()
        sync_narrative_findings(db, report_id=report.id, section=section, actor_user_id=user.id)
        section.version += 1
        section.updated_by = user.id
        audit(db, actor=user, action="TYPED_NOTE_APPENDED_TO_NARRATIVE", target_type="REPORT_SECTION", target_id=section.id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "finding_type": finding_type, "derived_finding_id": finding.id})
    else:
        finding = Finding(
            report_id=report.id, section_id=None, finding_type=finding_type,
            statement=payload.statement, impact=payload.impact, confidence=payload.confidence,
            source_type="LEGACY", client_mutation_id=payload.client_mutation_id, created_by=user.id,
        )
        db.add(finding)
        db.flush()
        audit(db, actor=user, action="FINDING_CREATED", target_type="FINDING", target_id=finding.id, prospect_id=report.prospect_id, metadata={"report_id": report.id})
    _increment_report(report)
    db.commit()
    return {"id": finding.id, "version": section.version if payload.section_id else None, "narrative": section.narrative if payload.section_id else None}


@router.post("/reports/{report_id}/metrics", dependencies=[Depends(require_csrf)])
def create_metric(report_id: str, payload: MetricCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    metric = Metric(report_id=report.id, section_id=payload.section_id, created_by=user.id, **payload.model_dump(exclude={"section_id"}))
    db.add(metric)
    if payload.section_id:
        section = _get_section(db, payload.section_id)
        if section.report_id != report.id:
            raise HTTPException(400, "Section does not belong to report.")
        section.version += 1
        section.updated_by = user.id
    _increment_report(report)
    audit(db, actor=user, action="METRIC_CREATED", target_type="METRIC", target_id=metric.id, prospect_id=report.prospect_id, metadata={"report_id": report.id})
    db.commit()
    return {"id": metric.id}


@router.get("/capabilities")
def list_capabilities(domain: str | None = None, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    stmt = select(Capability).order_by(Capability.domain, Capability.name)
    if "ADMIN" not in user_roles(db, user.id):
        stmt = stmt.where(Capability.status != "RETIRED")
    if domain:
        stmt = stmt.where(Capability.domain == domain)
    items = list(db.scalars(stmt).all())
    return [{"id": c.id, "capability_code": c.capability_code, "name": c.name, "domain": c.domain, "controlled_description": c.controlled_description, "typical_prerequisites": c.typical_prerequisites, "limitations": c.limitations, "status": c.status, "source": c.source, "product_version": c.product_version, "review_due_at": _iso(c.review_due_at), "last_reviewed_at": _iso(c.last_reviewed_at), "version": c.version} for c in items]


@router.post("/admin/capabilities", dependencies=[Depends(require_csrf)])
def create_capability(payload: CapabilityCreate, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    capability = Capability(**payload.model_dump())
    db.add(capability)
    try:
        audit(db, actor=actor, action="CAPABILITY_CREATED", target_type="CAPABILITY", target_id=capability.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Capability code already exists.")
    return {"id": capability.id}


@router.patch("/admin/capabilities/{capability_id}", dependencies=[Depends(require_csrf)])
def update_capability(capability_id: str, payload: CapabilityUpdate, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    capability = db.get(Capability, capability_id)
    if not capability:
        raise HTTPException(404, "Capability not found.")
    data = payload.model_dump(exclude_unset=True)
    expected_version = data.pop("expected_version", None)
    if expected_version is not None and expected_version != capability.version:
        raise HTTPException(status_code=409, detail={"message": "Capability changed since it was loaded.", "current_version": capability.version})
    for key, value in data.items():
        setattr(capability, key, value)
    capability.version += 1
    audit(db, actor=actor, action="CAPABILITY_UPDATED", target_type="CAPABILITY", target_id=capability.id, metadata={"status": capability.status})
    db.commit()
    return {"ok": True, "version": capability.version}


@router.post("/admin/capabilities/{capability_id}/review", dependencies=[Depends(require_csrf)])
def review_capability(capability_id: str, payload: ReviewDecision, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    capability = db.get(Capability, capability_id)
    if not capability:
        raise HTTPException(404, "Capability not found.")
    capability.status = "APPROVED" if payload.decision == "APPROVED" else "RETIRED"
    capability.last_reviewed_at = utcnow()
    capability.last_reviewed_by = actor.id
    capability.version += 1
    knowledge = db.scalar(select(KnowledgeEntry).where(KnowledgeEntry.source_ref == f"capability:{capability.capability_code}"))
    if knowledge:
        knowledge.approval_state = payload.decision
        knowledge.approved_by = actor.id if payload.decision == "APPROVED" else None
    audit(db, actor=actor, action="CAPABILITY_REVIEWED", target_type="CAPABILITY", target_id=capability.id, metadata={"decision": payload.decision, "note": payload.note})
    db.commit()
    return {"ok": True, "status": capability.status, "version": capability.version}


@router.post("/reports/{report_id}/capability-mappings", dependencies=[Depends(require_csrf)])
def create_mapping(report_id: str, payload: CapabilityMappingCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    capability = db.get(Capability, payload.capability_id)
    if not capability:
        raise HTTPException(400, "Invalid Cloud Inventory capability.")
    if capability.status != "APPROVED":
        raise HTTPException(409, "Only approved capabilities can be mapped to Current Operations Narrative entries or guided observations.")
    source = _resolve_mapping_source(
        db,
        report,
        section_id=payload.section_id,
        source_ref=payload.source_ref,
        finding_id=payload.finding_id,
    )
    existing = db.scalar(
        select(CapabilityMapping).where(
            CapabilityMapping.report_id == report.id,
            CapabilityMapping.capability_id == capability.id,
            CapabilityMapping.source_ref == source["source_ref"],
        )
    )
    if existing:
        raise HTTPException(409, "This capability is already mapped to the selected observation or finding.")
    mapping = CapabilityMapping(
        report_id=report.id,
        section_id=source["section_id"],
        finding_id=source["finding_id"],
        source_ref=source["source_ref"],
        source_type=source["source_type"],
        source_label=source["source_label"],
        source_statement=source["source_statement"],
        capability_id=capability.id,
        rationale=payload.rationale,
        prerequisites=payload.prerequisites,
        created_by=user.id,
    )
    db.add(mapping)
    _increment_report(report)
    audit(
        db,
        actor=user,
        action="CAPABILITY_MAPPING_CREATED",
        target_type="CAPABILITY_MAPPING",
        target_id=mapping.id,
        prospect_id=report.prospect_id,
        metadata={"report_id": report.id, "source_ref": source["source_ref"], "source_type": source["source_type"]},
    )
    db.commit()
    return {"id": mapping.id}


@router.post("/reports/{report_id}/capability-mappings/{mapping_id}/review", dependencies=[Depends(require_csrf)])
def review_mapping(report_id: str, mapping_id: str, payload: ReviewDecision, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "REVIEWER")
    mapping = db.get(CapabilityMapping, mapping_id)
    if not mapping or mapping.report_id != report.id:
        raise HTTPException(404, "Mapping not found.")
    mapping.approval_state = payload.decision
    mapping.approved_by = user.id
    db.add(Approval(report_id=report.id, target_type="CAPABILITY_MAPPING", target_id=mapping.id, target_version=1, decision=payload.decision, decided_by=user.id, note=payload.note))
    _increment_report(report)
    audit(db, actor=user, action="CAPABILITY_MAPPING_REVIEWED", target_type="CAPABILITY_MAPPING", target_id=mapping.id, prospect_id=report.prospect_id, metadata={"decision": payload.decision})
    db.commit()
    return {"ok": True}


@router.post("/reports/{report_id}/benefits", dependencies=[Depends(require_csrf)])
def create_benefit(report_id: str, payload: BenefitCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    source = _resolve_benefit_source(
        db,
        report,
        section_id=payload.section_id,
        finding_id=payload.finding_id,
        capability_mapping_id=payload.capability_mapping_id,
        source_ref=payload.source_ref,
    )
    if payload.measure_type == "QUANTITATIVE":
        if source["source_type"] != "METRIC":
            raise HTTPException(400, "Quantitative benefits must be based on a recorded metric.")
        if not payload.formula or not payload.assumptions:
            raise HTTPException(400, "Quantitative benefits require a measurement formula and explicit assumptions.")
    benefit = Benefit(
        report_id=report.id,
        section_id=source["section_id"],
        finding_id=source["finding_id"],
        capability_mapping_id=source["capability_mapping_id"],
        source_ref=source["source_ref"],
        source_type=source["source_type"],
        source_label=source["source_label"],
        source_statement=source["source_statement"],
        statement=payload.statement,
        category=payload.category,
        measure_type=payload.measure_type,
        formula=payload.formula,
        assumptions=payload.assumptions,
        confidence=payload.confidence,
        approval_state="PENDING",
        created_by=user.id,
    )
    db.add(benefit)
    _increment_report(report)
    audit(
        db,
        actor=user,
        action="BENEFIT_CREATED",
        target_type="BENEFIT",
        target_id=benefit.id,
        prospect_id=report.prospect_id,
        metadata={"report_id": report.id, "section_id": benefit.section_id, "source_ref": benefit.source_ref},
    )
    db.commit()
    return {"id": benefit.id, "approval_state": benefit.approval_state}


@router.post("/reports/{report_id}/benefits/{benefit_id}/review", dependencies=[Depends(require_csrf)])
def review_benefit(report_id: str, benefit_id: str, payload: ReviewDecision, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "REVIEWER")
    benefit = db.get(Benefit, benefit_id)
    if not benefit or benefit.report_id != report.id:
        raise HTTPException(404, "Benefit not found.")
    benefit.approval_state = payload.decision
    benefit.approved_by = user.id if payload.decision == "APPROVED" else None
    db.add(Approval(report_id=report.id, section_id=benefit.section_id, target_type="BENEFIT", target_id=benefit.id, target_version=1, decision=payload.decision, decided_by=user.id, note=payload.note))
    _increment_report(report)
    audit(db, actor=user, action="BENEFIT_REVIEWED", target_type="BENEFIT", target_id=benefit.id, prospect_id=report.prospect_id, metadata={"decision": payload.decision})
    db.commit()
    return {"ok": True, "approval_state": benefit.approval_state}


@router.put("/reports/{report_id}/demo-settings", dependencies=[Depends(require_csrf)])
def upsert_demo_settings(
    report_id: str,
    payload: DemoPlanSettingsUpsert,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    item = db.get(DemoPlanSettings, report.id)
    if item:
        if payload.expected_version is not None and payload.expected_version != item.version:
            raise HTTPException(409, detail={"message": "Demo settings changed in another session.", "current_version": item.version})
        item.audience = payload.audience
        item.duration_minutes = payload.duration_minutes
        item.additional_priorities = payload.additional_priorities
        item.version += 1
        item.updated_by = user.id
    else:
        if payload.expected_version not in {None, 0}:
            raise HTTPException(409, detail={"message": "Demo settings do not yet exist.", "current_version": None})
        item = DemoPlanSettings(
            report_id=report.id,
            audience=payload.audience,
            duration_minutes=payload.duration_minutes,
            additional_priorities=payload.additional_priorities,
            version=1,
            updated_by=user.id,
        )
        db.add(item)
    _increment_report(report)
    audit(db, actor=user, action="DEMO_SETTINGS_UPDATED", target_type="REPORT", target_id=report.id, prospect_id=report.prospect_id, metadata={"version": item.version})
    db.commit()
    return {"audience": item.audience, "duration_minutes": item.duration_minutes, "additional_priorities": item.additional_priorities, "version": item.version, "report_revision": report.revision}


@router.put("/reports/{report_id}/sections/{section_id}/demo-priority", dependencies=[Depends(require_csrf)])
def upsert_demo_section_priority(
    report_id: str,
    section_id: str,
    payload: DemoSectionPriorityUpsert,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = _get_section(db, section_id)
    if section.report_id != report.id:
        raise HTTPException(404, "Section not found.")
    item = db.scalar(select(DemoSectionPriority).where(DemoSectionPriority.report_id == report.id, DemoSectionPriority.section_id == section.id))
    if item:
        if payload.expected_version is not None and payload.expected_version != item.version:
            raise HTTPException(409, detail={"message": "Demo priority changed in another session.", "current_version": item.version})
        item.priority = payload.priority
        item.user_notes = payload.user_notes
        item.constraints = payload.constraints
        item.estimated_minutes = payload.estimated_minutes
        item.version += 1
        item.updated_by = user.id
    else:
        item = DemoSectionPriority(
            report_id=report.id, section_id=section.id, priority=payload.priority,
            user_notes=payload.user_notes, constraints=payload.constraints,
            estimated_minutes=payload.estimated_minutes, version=1, updated_by=user.id,
        )
        db.add(item)
    _increment_report(report)
    audit(db, actor=user, action="DEMO_SECTION_PRIORITY_UPDATED", target_type="REPORT_SECTION", target_id=section.id, prospect_id=report.prospect_id, metadata={"priority": item.priority, "version": item.version})
    db.commit()
    return {"id": item.id, "section_id": item.section_id, "priority": item.priority, "user_notes": item.user_notes, "constraints": item.constraints, "estimated_minutes": item.estimated_minutes, "version": item.version, "report_revision": report.revision}


@router.get("/reports/{report_id}/demo-plan-versions")
def list_demo_plan_versions(report_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    items = list(db.scalars(select(DemoPlanVersion).where(DemoPlanVersion.report_id == report.id).order_by(DemoPlanVersion.version.desc())).all())
    return [{"id": item.id, "version": item.version, "content": item.content, "source_type": item.source_type, "source_refs": item.source_refs, "is_current": item.is_current, "created_at": _iso(item.created_at)} for item in items]



def _validate_evidence_upload(data: bytes, filename: str, mime_type: str) -> None:
    suffix = Path(filename).suffix.lower()
    if mime_type.startswith("image/"):
        return  # Decoded by _process_image before the transaction commits.
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise HTTPException(415, "The file extension is PDF but the content is not a valid PDF header.")
        return
    if suffix in {".docx", ".xlsx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                expected = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
                if expected not in names:
                    raise HTTPException(415, f"The uploaded {suffix[1:].upper()} file is not structurally valid.")
        except zipfile.BadZipFile:
            raise HTTPException(415, f"The uploaded {suffix[1:].upper()} file is not structurally valid.")
        return
    if suffix in {".csv", ".txt", ".md", ".json", ".xml"}:
        if b"\x00" in data[:10000]:
            raise HTTPException(415, "Text attachments cannot contain binary null bytes.")
        return
    raise HTTPException(415, "Unsupported attachment type. Use an image, PDF, DOCX, XLSX, CSV, TXT, Markdown, JSON, or XML file.")


def _process_image(data: bytes) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
        if img.mode not in {"RGB", "L"}:
            img = img.convert("RGB")
        out = io.BytesIO()
        if img.mode == "L":
            img = img.convert("RGB")
        img.save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue(), img.width, img.height


@router.post("/reports/{report_id}/evidence", dependencies=[Depends(require_csrf)])
async def upload_evidence(
    report_id: str,
    section_id: str | None = Form(None),
    caption: str | None = Form(None),
    placement: str = Form("INLINE"),
    classification: str = Form("CONFIDENTIAL"),
    file: UploadFile = File(...),
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = None
    if section_id:
        section = _get_section(db, section_id)
        if section.report_id != report.id:
            raise HTTPException(400, "Section does not belong to report.")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "File exceeds configured upload limit.")
    filename = safe_filename(file.filename or "upload.bin")
    mime = file.content_type or "application/octet-stream"
    _validate_evidence_upload(data, filename, mime)
    evidence_type = "PHOTO" if mime.startswith("image/") else "ATTACHMENT"
    extraction = extract_text(data, filename, mime) if evidence_type == "ATTACHMENT" else None
    item = EvidenceItem(
        prospect_id=report.prospect_id, report_id=report.id, section_id=section_id,
        evidence_type=evidence_type, caption=caption, placement=placement.upper(),
        classification=classification.upper(), status="PROCESSING", created_by=user.id,
        extraction_state=extraction.state if extraction else "NOT_APPLICABLE",
        extracted_text=extraction.text if extraction else None,
    )
    db.add(item)
    db.flush()
    storage = _object_storage_or_503(settings)
    original_key = build_storage_key(report.prospect_id, "evidence", item.id, filename)
    stored = storage.put_bytes(original_key, data, mime)
    original = FileObject(evidence_id=item.id, prospect_id=report.prospect_id, storage_key=stored.key, variant="ORIGINAL", file_name=filename, mime_type=stored.mime_type, size_bytes=stored.size, sha256=stored.sha256, scan_state="NOT_CONFIGURED")
    db.add(original)
    if mime.startswith("image/"):
        try:
            web_bytes, width, height = _process_image(data)
        except Exception:
            storage.delete(original_key)
            db.rollback()
            raise HTTPException(400, "The uploaded image could not be decoded.")
        web_name = f"{Path(filename).stem}-web.jpg"
        web_key = build_storage_key(report.prospect_id, "evidence", item.id, web_name)
        web_stored = storage.put_bytes(web_key, web_bytes, "image/jpeg")
        db.add(FileObject(evidence_id=item.id, prospect_id=report.prospect_id, storage_key=web_stored.key, variant="WEB", file_name=web_name, mime_type="image/jpeg", size_bytes=web_stored.size, sha256=web_stored.sha256, width=width, height=height, scan_state="NOT_CONFIGURED"))
    item.status = "READY"
    if section:
        section.updated_by = user.id
        section.version += 1
    _increment_report(report)
    audit(db, actor=user, action="EVIDENCE_UPLOADED", target_type="EVIDENCE", target_id=item.id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "section_id": section_id, "file_name": filename, "size": len(data)})
    db.commit()
    return {"id": item.id, "status": item.status, "file_name": filename, "extraction_state": item.extraction_state}


@router.post("/reports/{report_id}/evidence/{evidence_id}/review", dependencies=[Depends(require_csrf)])
def review_evidence(report_id: str, evidence_id: str, payload: EvidenceReviewRequest, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "REVIEWER")
    evidence = db.get(EvidenceItem, evidence_id)
    if not evidence or evidence.report_id != report.id:
        raise HTTPException(404, "Evidence not found.")
    evidence.ai_inclusion_recommendation = {"include": payload.include_in_report, "rationale": payload.rationale, "reviewed_by": user.id, "reviewed_at": _iso(utcnow())}
    if not payload.include_in_report:
        evidence.placement = "SUPPORTING_ONLY"
    audit(db, actor=user, action="EVIDENCE_REVIEWED", target_type="EVIDENCE", target_id=evidence.id, prospect_id=report.prospect_id, metadata=evidence.ai_inclusion_recommendation)
    db.commit()
    return {"ok": True, "placement": evidence.placement}


@router.post("/reports/{report_id}/evidence/bulk", dependencies=[Depends(require_csrf)])
def bulk_manage_evidence(
    report_id: str,
    payload: EvidenceBulkAction,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    items = list(
        db.scalars(
            select(EvidenceItem).where(
                EvidenceItem.report_id == report.id,
                EvidenceItem.id.in_(payload.evidence_ids),
            )
        ).all()
    )
    if len(items) != len(set(payload.evidence_ids)):
        raise HTTPException(404, "One or more selected evidence items are unavailable.")

    touched_section_ids = {item.section_id for item in items if item.section_id}
    if payload.action == "MOVE":
        if not payload.target_section_id:
            raise HTTPException(400, "A destination report section is required.")
        target = _get_section(db, payload.target_section_id)
        if target.report_id != report.id or target.state == "REMOVED":
            raise HTTPException(400, "The destination report section is unavailable.")
        touched_section_ids.add(target.id)
        for item in items:
            item.section_id = target.id
        action_name = "EVIDENCE_BULK_MOVED"
        metadata = {"report_id": report.id, "evidence_ids": payload.evidence_ids, "target_section_id": target.id}
    else:
        storage = _object_storage_or_503(settings)
        file_objects = list(db.scalars(select(FileObject).where(FileObject.evidence_id.in_(payload.evidence_ids))).all())
        for file_obj in file_objects:
            try:
                storage.delete(file_obj.storage_key)
            except FileNotFoundError:
                pass
            db.delete(file_obj)
        db.flush()
        for item in items:
            db.delete(item)
        action_name = "EVIDENCE_BULK_DELETED"
        metadata = {"report_id": report.id, "evidence_ids": payload.evidence_ids, "deleted_count": len(items)}

    for section_id in touched_section_ids:
        section = db.get(ReportSection, section_id)
        if section:
            section.version += 1
            section.updated_by = user.id
    _increment_report(report)
    audit(
        db, actor=user, action=action_name, target_type="REPORT", target_id=report.id,
        prospect_id=report.prospect_id, metadata=metadata,
    )
    db.commit()
    return {
        "ok": True, "action": payload.action, "affected_count": len(items),
        "target_section_id": payload.target_section_id if payload.action == "MOVE" else None,
        "report_revision": report.revision,
    }


@router.get("/files/{file_id}")
def download_file(file_id: str, inline: bool = False, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    file_obj = db.get(FileObject, file_id)
    if not file_obj:
        raise HTTPException(404, "File not found.")
    require_prospect_access(db, user, file_obj.prospect_id)
    storage = _object_storage_or_503(settings)
    if not inline:
        url = storage.signed_download_url(file_obj.storage_key, file_obj.file_name, file_obj.mime_type)
        if url:
            return RedirectResponse(url)
    data = storage.get_bytes(file_obj.storage_key)
    disposition = "inline" if inline else "attachment"
    return StreamingResponse(
        io.BytesIO(data),
        media_type=file_obj.mime_type,
        headers={"Content-Disposition": f'{disposition}; filename="{safe_filename(file_obj.file_name)}"'},
    )


@router.post("/reports/{report_id}/validate", dependencies=[Depends(require_csrf)])
def run_validation(report_id: str, payload: ValidationRequest, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "REVIEWER" if payload.final_requested else "CONTRIBUTOR")
    issues = validate_report(db, report, payload.final_requested)
    passed = validation_passed(issues)
    run = ValidationRun(report_id=report.id, report_revision=report.revision, final_requested=payload.final_requested, passed=passed, issues=issues, created_by=user.id)
    db.add(run)
    audit(db, actor=user, action="REPORT_VALIDATED", target_type="VALIDATION_RUN", target_id=run.id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "final_requested": payload.final_requested, "passed": passed, "issue_count": len(issues)})
    db.commit()
    return {"id": run.id, "passed": passed, "issues": issues}


@router.post("/reports/{report_id}/publications", dependencies=[Depends(require_csrf)])
def create_publication(report_id: str, payload: PublicationRequest, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "OWNER" if payload.is_final else "REVIEWER")
    issues = validate_report(db, report, payload.is_final)
    passed = validation_passed(issues)
    validation = ValidationRun(report_id=report.id, report_revision=report.revision, final_requested=payload.is_final, passed=passed, issues=issues, created_by=user.id)
    db.add(validation)
    db.flush()
    if payload.is_final and not passed:
        db.commit()
        raise HTTPException(status_code=422, detail={"message": "Final publication validation failed.", "validation_run_id": validation.id, "issues": issues})
    publication = Publication(report_id=report.id, report_revision=report.revision, publication_type=payload.publication_type, is_final=payload.is_final, status="QUEUED", validation_run_id=validation.id, requested_by=user.id)
    db.add(publication)
    db.flush()
    enqueue(db, "publication.generate", {"publication_id": publication.id}, queue_name="PUBLICATION", priority=40)
    knowledge_candidates = _create_knowledge_candidates(db, report, user) if payload.is_final else 0
    audit(db, actor=user, action="PUBLICATION_REQUESTED", target_type="PUBLICATION", target_id=publication.id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "type": payload.publication_type, "is_final": payload.is_final, "knowledge_candidates": knowledge_candidates})
    db.commit()
    return {"id": publication.id, "status": publication.status, "validation": {"passed": passed, "issues": issues}}


@router.get("/publications/{publication_id}")
def get_publication(publication_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    publication = db.get(Publication, publication_id)
    if not publication:
        raise HTTPException(404, "Publication not found.")
    report = _get_report(db, publication.report_id)
    require_report_access(db, user, report)
    return {
        "id": publication.id,
        "status": publication.status,
        "publication_type": publication.publication_type,
        "is_final": publication.is_final,
        "report_revision": publication.report_revision,
        "docx_file_id": publication.docx_file_id,
        "pdf_file_id": publication.pdf_file_id,
        "error": publication.error,
        "created_at": _iso(publication.created_at),
        "completed_at": _iso(publication.completed_at),
        "dismissed_at": _iso(publication.dismissed_at),
    }


@router.post("/reports/{report_id}/publications/{publication_id}/dismiss", dependencies=[Depends(require_csrf)])
def dismiss_failed_publication(
    report_id: str,
    publication_id: str,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "REVIEWER")
    publication = db.get(Publication, publication_id)
    if not publication or publication.report_id != report.id:
        raise HTTPException(404, "Publication not found.")
    if publication.status != "FAILED":
        raise HTTPException(409, "Only failed publication attempts can be dismissed.")
    if publication.dismissed_at is None:
        publication.dismissed_at = utcnow()
        publication.dismissed_by = user.id
        audit(
            db,
            actor=user,
            action="PUBLICATION_FAILURE_DISMISSED",
            target_type="PUBLICATION",
            target_id=publication.id,
            prospect_id=report.prospect_id,
            metadata={"report_id": report.id, "publication_type": publication.publication_type},
        )
        db.commit()
    return {"ok": True, "dismissed_at": _iso(publication.dismissed_at)}


@router.delete("/reports/{report_id}", dependencies=[Depends(require_csrf)])
def permanently_delete_report(report_id: str, payload: ReportDeleteRequest, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "OWNER")
    if payload.confirm_title.strip() != report.title:
        raise HTTPException(400, "Report title confirmation does not match.")
    if report.state not in {"DRAFT", "MERGED"}:
        raise HTTPException(409, "Only draft reports or merged source reports can be permanently deleted.")
    evidence_ids = list(db.scalars(select(EvidenceItem.id).where(EvidenceItem.report_id == report.id)).all())
    evidence_files = list(db.scalars(select(FileObject).where(FileObject.evidence_id.in_(evidence_ids))).all()) if evidence_ids else []
    publications = list(db.scalars(select(Publication).where(Publication.report_id == report.id)).all())
    publication_file_ids = {file_id for publication in publications for file_id in (publication.docx_file_id, publication.pdf_file_id) if file_id}
    publication_files = list(db.scalars(select(FileObject).where(FileObject.id.in_(publication_file_ids))).all()) if publication_file_ids else []
    all_files = {item.id: item for item in evidence_files + publication_files}
    storage = _object_storage_or_503(settings)
    for file_obj in all_files.values():
        try:
            storage.delete(file_obj.storage_key)
        except FileNotFoundError:
            pass
    prospect_id = report.prospect_id
    title = report.title
    db.delete(report)
    db.flush()
    for file_obj in publication_files:
        if db.get(FileObject, file_obj.id):
            db.delete(file_obj)
    audit(db, actor=user, action="REPORT_PERMANENT_DELETE", target_type="REPORT", target_id=report_id, prospect_id=prospect_id, metadata={"title": title, "files_deleted": len(all_files)})
    db.commit()
    return {"ok": True, "deleted_report_id": report_id, "files_deleted": len(all_files)}


@router.post("/reports/merge", dependencies=[Depends(require_csrf)])
def merge_reports(payload: MergeRequest, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    target = _get_report(db, payload.target_report_id)
    require_report_access(db, user, target, "OWNER")
    sources = []
    for source_id in payload.source_report_ids:
        source = _get_report(db, source_id)
        require_report_access(db, user, source, "OWNER")
        if source.prospect_id != target.prospect_id or source.id == target.id:
            raise HTTPException(400, "Reports must be different reports for the same prospect.")
        sources.append(source)
    operation = MergeOperation(target_report_id=target.id, source_report_ids=[s.id for s in sources], status="RUNNING", created_by=user.id)
    db.add(operation)
    db.flush()
    conflicts: list[dict[str, Any]] = []
    target_sections = {s.stable_key: s for s in db.scalars(select(ReportSection).where(ReportSection.report_id == target.id)).all()}
    storage = _object_storage_or_503(settings)
    for source in sources:
        for source_section in db.scalars(select(ReportSection).where(ReportSection.report_id == source.id).order_by(ReportSection.display_order)).all():
            target_section = target_sections.get(source_section.stable_key)
            if not target_section:
                target_section = ReportSection(report_id=target.id, section_template_id=source_section.section_template_id, stable_key=source_section.stable_key, title=source_section.title, process_module=source_section.process_module, display_order=(max([s.display_order for s in target_sections.values()] or [0]) + 10), state=source_section.state, required_on_final=source_section.required_on_final, narrative=source_section.narrative, created_by=user.id, updated_by=user.id)
                db.add(target_section)
                db.flush()
                target_sections[target_section.stable_key] = target_section
            elif source_section.narrative.strip():
                if target_section.narrative.strip() and target_section.narrative.strip() != source_section.narrative.strip():
                    conflicts.append({"section": target_section.title, "source_report_id": source.id, "type": "NARRATIVE_COMBINED"})
                    target_section.narrative += f"\n\n--- Contributor report {source.title} ---\n{source_section.narrative}"
                elif not target_section.narrative.strip():
                    target_section.narrative = source_section.narrative
            sync_narrative_findings(db, report_id=target.id, section=target_section, actor_user_id=user.id)
            target_section.version += 1
            db.add(MergeLineage(merge_operation_id=operation.id, target_type="REPORT_SECTION", target_id=target_section.id, source_report_id=source.id, source_type="REPORT_SECTION", source_id=source_section.id, source_version=source_section.version))
            for finding in db.scalars(select(Finding).where(Finding.report_id == source.id, Finding.section_id == source_section.id, Finding.source_type != NARRATIVE_DERIVED_SOURCE)).all():
                clone = Finding(report_id=target.id, section_id=target_section.id, finding_type=finding.finding_type, statement=finding.statement, impact=finding.impact, confidence=finding.confidence, status=finding.status, source_type=finding.source_type, created_by=finding.created_by)
                db.add(clone)
                db.flush()
                db.add(MergeLineage(merge_operation_id=operation.id, target_type="FINDING", target_id=clone.id, source_report_id=source.id, source_type="FINDING", source_id=finding.id, source_version=None))
            for metric in db.scalars(select(Metric).where(Metric.report_id == source.id, Metric.section_id == source_section.id)).all():
                db.add(Metric(report_id=target.id, section_id=target_section.id, name=metric.name, value_numeric=metric.value_numeric, value_text=metric.value_text, unit=metric.unit, period=metric.period, source=metric.source, confidence=metric.confidence, created_by=metric.created_by))
            for evidence in db.scalars(select(EvidenceItem).where(EvidenceItem.report_id == source.id, EvidenceItem.section_id == source_section.id)).all():
                clone_e = EvidenceItem(prospect_id=target.prospect_id, report_id=target.id, section_id=target_section.id, evidence_type=evidence.evidence_type, caption=evidence.caption, placement=evidence.placement, classification=evidence.classification, status=evidence.status, extraction_state=evidence.extraction_state, extracted_text=evidence.extracted_text, ai_inclusion_recommendation=evidence.ai_inclusion_recommendation, created_by=evidence.created_by)
                db.add(clone_e)
                db.flush()
                for file_obj in db.scalars(select(FileObject).where(FileObject.evidence_id == evidence.id)).all():
                    data = storage.get_bytes(file_obj.storage_key)
                    new_key = build_storage_key(target.prospect_id, "evidence", clone_e.id, file_obj.file_name)
                    stored = storage.put_bytes(new_key, data, file_obj.mime_type)
                    db.add(FileObject(evidence_id=clone_e.id, prospect_id=target.prospect_id, storage_key=stored.key, variant=file_obj.variant, file_name=file_obj.file_name, mime_type=file_obj.mime_type, size_bytes=stored.size, sha256=stored.sha256, width=file_obj.width, height=file_obj.height, scan_state=file_obj.scan_state))
                db.add(MergeLineage(merge_operation_id=operation.id, target_type="EVIDENCE", target_id=clone_e.id, source_report_id=source.id, source_type="EVIDENCE", source_id=evidence.id, source_version=None))
        if payload.delete_sources_after_merge:
            source.state = "MERGED"
            source.merged_into_report_id = target.id
            source.recovery_delete_after = utcnow() + timedelta(days=settings.merge_source_recovery_days)
    operation.conflict_summary = {"conflicts": conflicts, "count": len(conflicts)}
    operation.status = "COMPLETED"
    operation.completed_at = utcnow()
    _increment_report(target)
    audit(db, actor=user, action="REPORTS_MERGED", target_type="MERGE_OPERATION", target_id=operation.id, prospect_id=target.prospect_id, metadata={"target_report_id": target.id, "source_report_ids": [s.id for s in sources], "conflicts": conflicts})
    db.commit()
    return {"id": operation.id, "status": operation.status, "conflicts": conflicts, "target_report_revision": target.revision}


@router.get("/ai/status")
def ai_status(user: User = Depends(enforce_password_changed), settings: Settings = Depends(get_settings)):
    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    return {"enabled": settings.ai_enabled, "confidential_content_enabled": settings.ai_confidential_content_enabled, "data_control_mode": settings.openai_data_control_mode, "model": settings.openai_model, "policy": decision.as_dict()}


@router.get("/reports/{report_id}/sections/{section_id}/ai-wording/current")
def get_current_ai_wording(
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

    snapshot = build_observation_snapshot(db, report, section, [])
    fingerprint = str(snapshot.get("source_fingerprint") or observation_source_fingerprint(snapshot))
    suggestion = _find_current_observation_suggestion(db, report.id, section.id, fingerprint)
    active_job = db.scalar(
        select(AiJob)
        .where(
            AiJob.report_id == report.id,
            AiJob.section_id == section.id,
            AiJob.purpose == "OBSERVATION_ENHANCEMENT",
            AiJob.source_fingerprint == fingerprint,
            AiJob.status.in_(["QUEUED", "RUNNING", "VERIFYING"]),
        )
        .order_by(AiJob.created_at.desc())
    )
    if active_job:
        active_suggestion = db.scalar(
            select(AiSuggestion)
            .where(AiSuggestion.ai_job_id == active_job.id)
            .order_by(AiSuggestion.created_at.desc())
        )
        return _serialize_ai_job(
            active_job,
            active_suggestion,
            available=True,
            is_current=True,
            is_stale=False,
            restored=True,
            current_source_fingerprint=fingerprint,
            message="The existing AI wording request is still processing.",
        )

    if suggestion:
        job = db.get(AiJob, suggestion.ai_job_id)
        if not job:
            raise HTTPException(409, "The saved AI wording no longer has a processing record.")
        db.commit()
        return _serialize_ai_job(
            job,
            suggestion,
            available=True,
            is_current=True,
            is_stale=False,
            restored=True,
            current_source_fingerprint=fingerprint,
            message="Saved AI wording restored because the written source content has not changed.",
        )

    stale = _find_latest_stale_observation_suggestion(db, report.id, section.id, fingerprint)
    if stale:
        stale_job = db.get(AiJob, stale.ai_job_id)
        if not stale_job:
            raise HTTPException(409, "The previous AI wording no longer has a processing record.")
        db.commit()
        return _serialize_ai_job(
            stale_job,
            stale,
            available=True,
            is_current=False,
            is_stale=True,
            restored=True,
            current_source_fingerprint=fingerprint,
            message="Previous AI wording exists, but the written source content has changed.",
        )

    return {
        "available": False,
        "is_current": False,
        "is_stale": False,
        "restored": False,
        "current_source_fingerprint": fingerprint,
        "message": "No saved AI wording exists for the current written source content.",
    }


@router.post("/reports/{report_id}/ai", dependencies=[Depends(require_csrf)], status_code=status.HTTP_202_ACCEPTED)
def request_ai(
    report_id: str,
    payload: AiRequest,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = db.get(ReportSection, payload.section_id) if payload.section_id else None
    if section and section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")

    context_snapshot = None
    parent_suggestion = None
    source_fingerprint = None
    if payload.purpose == "OBSERVATION_ENHANCEMENT":
        if not section:
            raise HTTPException(400, "Observation enhancement requires a report section.")
        if payload.evidence_ids:
            raise HTTPException(
                400,
                "AI enhancement is text-only. Photographs remain human-reviewed evidence and are never sent to AI.",
            )
        context_snapshot = build_observation_snapshot(db, report, section, [])
        source_fingerprint = str(
            context_snapshot.get("source_fingerprint") or observation_source_fingerprint(context_snapshot)
        )
        context_snapshot["source_fingerprint"] = source_fingerprint
        if payload.parent_suggestion_id:
            parent_suggestion = db.get(AiSuggestion, payload.parent_suggestion_id)
            if not parent_suggestion or parent_suggestion.report_id != report.id or parent_suggestion.section_id != section.id:
                raise HTTPException(400, "Parent AI suggestion does not belong to this section.")
            if parent_suggestion.purpose != "OBSERVATION_ENHANCEMENT":
                raise HTTPException(400, "Only an observation enhancement can be refined through this workflow.")
            if parent_suggestion.review_state != "PENDING":
                raise HTTPException(409, "Only the active pending AI wording can be refined.")
            if not (payload.instructions or "").strip():
                raise HTTPException(400, "Enter a refinement request before refining the AI wording.")
            parent_fingerprint = _observation_suggestion_fingerprint(parent_suggestion)
            if parent_fingerprint != source_fingerprint:
                raise HTTPException(
                    409,
                    "The written Current Operations sources changed after this wording was created. Generate updated wording before refining it.",
                )
        elif not payload.force_regenerate:
            existing_suggestion = _find_current_observation_suggestion(
                db, report.id, section.id, source_fingerprint
            )
            if existing_suggestion:
                existing_job = db.get(AiJob, existing_suggestion.ai_job_id)
                if existing_job:
                    db.commit()
                    return _serialize_ai_job(
                        existing_job,
                        existing_suggestion,
                        reused=True,
                        restored=True,
                        message="Saved AI wording restored because the written source content has not changed.",
                    )
            existing_job = db.scalar(
                select(AiJob)
                .where(
                    AiJob.report_id == report.id,
                    AiJob.section_id == section.id,
                    AiJob.purpose == "OBSERVATION_ENHANCEMENT",
                    AiJob.parent_suggestion_id.is_(None),
                    AiJob.source_fingerprint == source_fingerprint,
                    AiJob.status.in_(["QUEUED", "RUNNING", "VERIFYING"]),
                )
                .order_by(AiJob.created_at.desc())
            )
            if existing_job:
                return _serialize_ai_job(
                    existing_job,
                    None,
                    reused=True,
                    restored=True,
                    message="The existing AI wording request is still processing.",
                )

    elif payload.purpose == "SOLUTION_APPROACH":
        if not section:
            raise HTTPException(400, "Cloud Inventory approach generation requires a report section.")
        if payload.parent_suggestion_id:
            parent_suggestion = db.get(AiSuggestion, payload.parent_suggestion_id)
            if (
                not parent_suggestion
                or parent_suggestion.report_id != report.id
                or parent_suggestion.section_id != section.id
                or parent_suggestion.purpose != "SOLUTION_APPROACH"
            ):
                raise HTTPException(400, "Parent Cloud Inventory approach suggestion does not belong to this section.")
        context_snapshot = build_solution_snapshot(db, report, section)
        if not context_snapshot.get("operational_sources"):
            raise HTTPException(409, "Enter Current Operations Narrative content or guided responses before generating a Cloud Inventory approach.")
        if not context_snapshot.get("approved_capabilities"):
            raise HTTPException(409, "No approved Cloud Inventory capabilities are available for this operational area. Review the capability catalog first.")
    elif payload.purpose == "TARGETED_BENEFITS":
        if not section:
            raise HTTPException(400, "Targeted benefit generation requires a report section.")
        if payload.parent_suggestion_id:
            parent_suggestion = db.get(AiSuggestion, payload.parent_suggestion_id)
            if (
                not parent_suggestion
                or parent_suggestion.report_id != report.id
                or parent_suggestion.section_id != section.id
                or parent_suggestion.purpose != "TARGETED_BENEFITS"
            ):
                raise HTTPException(400, "Parent targeted-benefit suggestion does not belong to this section.")
        context_snapshot = build_targeted_benefits_snapshot(db, report, section)
        if not context_snapshot.get("operational_sources"):
            raise HTTPException(409, "Enter Current Operations Narrative content before generating targeted benefits.")
        if not context_snapshot.get("solution") and not context_snapshot.get("approved_mappings"):
            raise HTTPException(409, "Enter or accept a Cloud Inventory approach, or approve a capability mapping, before generating targeted benefits.")
    elif payload.purpose == "DEMO_PLAN":
        if section:
            raise HTTPException(400, "Demo-plan generation is report-level and must not specify a section.")
        if payload.parent_suggestion_id:
            parent_suggestion = db.get(AiSuggestion, payload.parent_suggestion_id)
            if not parent_suggestion or parent_suggestion.report_id != report.id or parent_suggestion.purpose != "DEMO_PLAN":
                raise HTTPException(400, "Parent demo-plan suggestion does not belong to this report.")
        context_snapshot = build_demo_plan_snapshot(db, report)
        eligible = [item for item in context_snapshot.get("sections") or [] if item.get("priority") != "DO_NOT_SHOW" and item.get("approved_mappings")]
        if not eligible:
            raise HTTPException(409, "Approve at least one capability mapping before generating a demo plan.")
    elif payload.purpose == "REPORT_QUALITY_REVIEW":
        if section:
            raise HTTPException(400, "Whole-report quality review must not specify a section.")
        context_snapshot = build_report_quality_snapshot(db, report)
        if not any(item.get("sources") or item.get("mappings") or item.get("benefits") for item in context_snapshot.get("sections") or []):
            raise HTTPException(409, "Enter report content before requesting a whole-report quality review.")
    elif payload.purpose == "EXECUTIVE_SUMMARY":
        if section:
            raise HTTPException(400, "Executive-summary generation is report-level and must not specify a section.")
        if payload.parent_suggestion_id:
            parent_suggestion = db.get(AiSuggestion, payload.parent_suggestion_id)
            if not parent_suggestion or parent_suggestion.report_id != report.id or parent_suggestion.purpose != "EXECUTIVE_SUMMARY":
                raise HTTPException(400, "Parent executive-summary suggestion does not belong to this report.")
        context_snapshot = build_executive_summary_snapshot(db, report)
        if not any(item.get("sources") or item.get("approved_mappings") or item.get("approved_benefits") for item in context_snapshot.get("sections") or []):
            raise HTTPException(409, "Enter and approve report content before generating an executive summary.")

    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    job = AiJob(
        report_id=report.id,
        section_id=payload.section_id,
        purpose=payload.purpose,
        instructions=payload.instructions,
        model=settings.openai_model,
        policy_decision=decision.as_dict(),
        context_snapshot=context_snapshot,
        parent_suggestion_id=parent_suggestion.id if parent_suggestion else None,
        source_fingerprint=source_fingerprint,
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
            status_code=403,
            detail={"message": decision.reason, "ai_job_id": job.id, "policy": decision.as_dict()},
        )
    queue_name = {
        "OBSERVATION_ENHANCEMENT": "FAST_TEXT",
    }.get(payload.purpose, "GENERAL_AI")
    priority = 10 if queue_name == "FAST_TEXT" else 100
    enqueue(
        db,
        "ai.generate",
        {"ai_job_id": job.id},
        max_attempts=3,
        queue_name=queue_name,
        priority=priority,
    )
    audit(
        db,
        actor=user,
        action="AI_REQUEST_QUEUED",
        target_type="AI_JOB",
        target_id=job.id,
        prospect_id=report.prospect_id,
        metadata={
            "purpose": payload.purpose,
            "selected_evidence_ids": payload.evidence_ids,
            "parent_suggestion_id": payload.parent_suggestion_id,
        },
    )
    db.commit()
    messages = {
        "SOLUTION_APPROACH": "Cloud Inventory approach queued for generation and human review.",
        "TARGETED_BENEFITS": "Targeted benefits queued for generation and human review.",
        "DEMO_PLAN": "Customer-specific demo plan queued for generation and human review.",
        "REPORT_QUALITY_REVIEW": "Whole-report quality review queued.",
        "EXECUTIVE_SUMMARY": "Executive summary queued for generation and human review.",
    }
    message = messages.get(payload.purpose, "AI enhancement queued for generation and human review.")
    return {
        "ai_job_id": job.id,
        "status": job.status,
        "message": message,
        "reused": False,
        "restored": False,
        "source_fingerprint": source_fingerprint,
    }


@router.get("/ai-jobs/{ai_job_id}")
def get_ai_job(ai_job_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    job = db.get(AiJob, ai_job_id)
    if not job:
        raise HTTPException(404, "AI job not found.")
    report = _get_report(db, job.report_id)
    require_report_access(db, user, report)
    suggestion = db.scalar(select(AiSuggestion).where(AiSuggestion.ai_job_id == job.id).order_by(AiSuggestion.created_at.desc()))
    return _serialize_ai_job(job, suggestion)


@router.post("/reports/{report_id}/ai-suggestions/{suggestion_id}/review", dependencies=[Depends(require_csrf)])
def review_ai(
    report_id: str,
    suggestion_id: str,
    payload: ReviewDecision,
    user: User = Depends(enforce_password_changed),
    db: Session = Depends(get_db),
):
    report = _get_report(db, report_id)
    suggestion = db.get(AiSuggestion, suggestion_id)
    if not suggestion or suggestion.report_id != report.id:
        raise HTTPException(404, "Suggestion not found.")
    # Observation enhancement is equivalent to a collaborative narrative edit,
    # so any report contributor may accept it. Other AI recommendations retain
    # the reviewer requirement.
    if suggestion.purpose in {"OBSERVATION_ENHANCEMENT", "TARGETED_BENEFITS", "DEMO_PLAN"}:
        require_report_access(db, user, report)
    else:
        require_report_access(db, user, report, "REVIEWER")

    if suggestion.review_state in {"STALE", "SUPERSEDED"}:
        raise HTTPException(409, "This AI wording is no longer the active candidate. Review the current saved wording instead.")

    suggestion.review_state = payload.decision
    suggestion.reviewed_by = user.id
    suggestion.review_note = payload.note
    suggestion.reviewed_at = utcnow()
    applied: dict[str, int | bool] = {"narrative": False, "solution": False, "mappings": 0, "benefits": 0, "demo_plan": False, "executive_summary": False}
    content = dict(suggestion.content or {})
    if payload.decision == "APPROVED" and not content.get("_applied"):
        target_section = db.get(ReportSection, suggestion.section_id) if suggestion.section_id else None
        suggested_text = str(content.get("enhanced_text") or content.get("suggested_text") or content.get("summary") or "").strip()

        if suggestion.purpose == "OBSERVATION_ENHANCEMENT":
            if not target_section:
                raise HTTPException(409, "The target section is no longer available.")
            if content.get("verification_status") != "PASSED" or not content.get("accept_allowed", False):
                raise HTTPException(409, "This AI-assisted current-operations revision contains unsupported claims and cannot be accepted. Refine or regenerate it first.")
            source_version = content.get("source_section_version")
            if suggestion.purpose == "OBSERVATION_ENHANCEMENT":
                stored_fingerprint = _observation_suggestion_fingerprint(suggestion)
                current_snapshot = build_observation_snapshot(db, report, target_section, [])
                current_fingerprint = str(
                    current_snapshot.get("source_fingerprint") or observation_source_fingerprint(current_snapshot)
                )
                if stored_fingerprint and stored_fingerprint != current_fingerprint:
                    raise HTTPException(
                        409,
                        "The written Current Operations sources changed after this wording was generated. Generate updated wording before accepting it.",
                    )
                if not stored_fingerprint and source_version is not None and int(source_version) != target_section.version:
                    raise HTTPException(409, "The section changed after this revision was generated. Generate a new revision before accepting it.")
            elif source_version is not None and int(source_version) != target_section.version:
                raise HTTPException(409, "The section changed after this revision was generated. Generate a new revision before accepting it.")
            if not suggested_text:
                raise HTTPException(409, "The current-operations revision does not contain usable text.")

            for current in db.scalars(
                select(SectionContentVersion).where(
                    SectionContentVersion.section_id == target_section.id,
                    SectionContentVersion.content_type == "CURRENT_OPERATIONS",
                    SectionContentVersion.is_current.is_(True),
                )
            ).all():
                current.is_current = False

            original_text = str(content.get("original_text") or target_section.narrative or "")
            existing_original = db.scalar(
                select(SectionContentVersion).where(
                    SectionContentVersion.section_id == target_section.id,
                    SectionContentVersion.content_type == "CURRENT_OPERATIONS",
                    SectionContentVersion.text == original_text,
                ).order_by(SectionContentVersion.version.desc())
            )
            if not existing_original:
                db.add(
                    SectionContentVersion(
                        report_id=report.id,
                        section_id=target_section.id,
                        content_type="CURRENT_OPERATIONS",
                        version=_next_content_version(db, target_section.id),
                        text=original_text,
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
                    section_id=target_section.id,
                    content_type="CURRENT_OPERATIONS",
                    version=_next_content_version(db, target_section.id),
                    text=suggested_text,
                    source_type="AI_ACCEPTED",
                    source_refs=content.get("source_refs") or [],
                    ai_suggestion_id=suggestion.id,
                    is_current=True,
                    created_by=user.id,
                )
            )
            target_section.narrative = suggested_text
            sync_narrative_findings(db, report_id=report.id, section=target_section, actor_user_id=user.id)
            target_section.version += 1
            target_section.updated_by = user.id
            applied["narrative"] = True

        elif suggestion.purpose == "SOLUTION_APPROACH":
            if not target_section:
                raise HTTPException(409, "The target section is no longer available.")
            if content.get("verification_status") != "PASSED" or not content.get("accept_allowed", False):
                raise HTTPException(409, "This Cloud Inventory approach contains unsupported claims or invalid mappings and cannot be accepted. Refine or regenerate it first.")
            source_version = content.get("source_section_version")
            if source_version is not None and int(source_version) != target_section.version:
                raise HTTPException(409, "The section changed after this Cloud Inventory approach was generated. Generate a new approach before accepting it.")
            if not suggested_text:
                raise HTTPException(409, "The Cloud Inventory approach does not contain usable text.")

            snapshot = dict(content.get("source_snapshot") or {})
            # Product and knowledge governance may change while an AI job is
            # awaiting review. Reject a stale suggestion instead of applying
            # wording based on superseded or unapproved reference content.
            for snap_cap in snapshot.get("approved_capabilities") or []:
                current_cap = db.get(Capability, snap_cap.get("id")) if snap_cap.get("id") else None
                if not current_cap or current_cap.status != "APPROVED" or current_cap.version != snap_cap.get("version"):
                    raise HTTPException(409, "The approved Cloud Inventory capability catalog changed after this approach was generated. Regenerate it before accepting.")
            for snap_knowledge in snapshot.get("approved_knowledge") or []:
                current_knowledge = db.get(KnowledgeEntry, snap_knowledge.get("id")) if snap_knowledge.get("id") else None
                if not current_knowledge or current_knowledge.approval_state != "APPROVED":
                    raise HTTPException(409, "Approved knowledge changed after this approach was generated. Regenerate it before accepting.")
                expected_updated = snap_knowledge.get("updated_at")
                current_updated = current_knowledge.updated_at.isoformat() if current_knowledge.updated_at else None
                if expected_updated and current_updated != expected_updated:
                    raise HTTPException(409, "Approved knowledge changed after this approach was generated. Regenerate it before accepting.")

            for current in db.scalars(
                select(SectionContentVersion).where(
                    SectionContentVersion.section_id == target_section.id,
                    SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH",
                    SectionContentVersion.is_current.is_(True),
                )
            ).all():
                current.is_current = False

            db.add(
                SectionContentVersion(
                    report_id=report.id,
                    section_id=target_section.id,
                    content_type="CLOUD_INVENTORY_APPROACH",
                    version=_next_content_version(db, target_section.id, "CLOUD_INVENTORY_APPROACH"),
                    text=suggested_text,
                    source_type="AI_ACCEPTED",
                    source_refs=content.get("source_refs") or [],
                    ai_suggestion_id=suggestion.id,
                    is_current=True,
                    created_by=user.id,
                )
            )

            for recommendation in content.get("capability_mappings") or []:
                if not isinstance(recommendation, dict):
                    continue
                capability_id = str(recommendation.get("capability_id") or "")
                source_ref = str(recommendation.get("source_ref") or "")
                capability = db.get(Capability, capability_id) if capability_id else None
                if not capability or capability.status != "APPROVED":
                    raise HTTPException(409, "A mapped Cloud Inventory capability is no longer approved.")
                source = _resolve_mapping_source(
                    db,
                    report,
                    section_id=target_section.id,
                    source_ref=source_ref,
                )
                existing = db.scalar(
                    select(CapabilityMapping).where(
                        CapabilityMapping.report_id == report.id,
                        CapabilityMapping.capability_id == capability.id,
                        CapabilityMapping.source_ref == source["source_ref"],
                    )
                )
                if existing:
                    existing.section_id = source["section_id"]
                    existing.finding_id = source["finding_id"]
                    existing.source_type = source["source_type"]
                    existing.source_label = source["source_label"]
                    existing.source_statement = source["source_statement"]
                    existing.rationale = str(recommendation.get("rationale") or "AI-assisted mapping approved with the solution approach.")
                    existing.prerequisites = str(recommendation.get("prerequisites") or "").strip() or None
                    existing.approval_state = "APPROVED"
                    existing.approved_by = user.id
                    existing.ai_suggestion_id = suggestion.id
                else:
                    db.add(
                        CapabilityMapping(
                            report_id=report.id,
                            section_id=source["section_id"],
                            finding_id=source["finding_id"],
                            source_ref=source["source_ref"],
                            source_type=source["source_type"],
                            source_label=source["source_label"],
                            source_statement=source["source_statement"],
                            capability_id=capability.id,
                            rationale=str(recommendation.get("rationale") or "AI-assisted mapping approved with the solution approach."),
                            prerequisites=str(recommendation.get("prerequisites") or "").strip() or None,
                            approval_state="APPROVED",
                            approved_by=user.id,
                            ai_suggestion_id=suggestion.id,
                            created_by=user.id,
                        )
                    )
                applied["mappings"] = int(applied["mappings"]) + 1

            target_section.version += 1
            target_section.updated_by = user.id
            applied["solution"] = True

        elif suggestion.purpose == "TARGETED_BENEFITS":
            if not target_section:
                raise HTTPException(409, "The target section is no longer available.")
            if content.get("verification_status") != "PASSED" or not content.get("accept_allowed", False):
                raise HTTPException(409, "These targeted benefits contain unsupported claims and cannot be accepted. Refine or regenerate them first.")
            source_version = content.get("source_section_version")
            if source_version is not None and int(source_version) != target_section.version:
                raise HTTPException(409, "The section changed after these benefits were generated. Generate new targeted benefits before accepting them.")
            source_revision = content.get("source_report_revision")
            if source_revision is not None and int(source_revision) != report.revision:
                raise HTTPException(409, "The report changed after these benefits were generated. Generate new targeted benefits before accepting them.")
            snapshot = dict(content.get("source_snapshot") or {})
            benefits_payload = list(content.get("benefits") or [])
            selected = set(payload.selected_item_indexes or range(len(benefits_payload)))
            for index, benefit_payload in enumerate(benefits_payload):
                if index not in selected or not isinstance(benefit_payload, dict):
                    continue
                statement = str(benefit_payload.get("statement") or "").strip()
                if not statement:
                    continue
                source_refs = list(benefit_payload.get("source_refs") or [])
                primary_ref = next((ref for ref in source_refs if str(ref).startswith("mapping:")), None)
                if primary_ref is None:
                    primary_ref = next((ref for ref in source_refs if str(ref).startswith(("finding:", "response:", "section:", "metric:", "solution:"))), None)
                if not primary_ref:
                    raise HTTPException(409, "A targeted benefit is no longer linked to a valid report source.")
                mapping_id = str(primary_ref).split(":", 1)[1] if str(primary_ref).startswith("mapping:") else None
                source = _resolve_benefit_source(
                    db, report, section_id=target_section.id, finding_id=None,
                    capability_mapping_id=mapping_id, source_ref=None if mapping_id else str(primary_ref),
                )
                measure_type = str(benefit_payload.get("measure_type") or "QUALITATIVE").upper()
                formula = str(benefit_payload.get("formula") or "").strip() or None
                assumptions = str(benefit_payload.get("assumptions") or "").strip() or None
                if measure_type == "QUANTITATIVE" and (source["source_type"] != "METRIC" or not formula or not assumptions):
                    raise HTTPException(409, "A quantitative benefit is missing a valid metric, formula, or assumptions.")
                exists = db.scalar(select(Benefit.id).where(Benefit.report_id == report.id, Benefit.section_id == target_section.id, Benefit.statement == statement))
                if exists:
                    continue
                db.add(Benefit(
                    report_id=report.id, section_id=target_section.id, finding_id=source["finding_id"],
                    capability_mapping_id=source["capability_mapping_id"], source_ref=source["source_ref"],
                    source_type=source["source_type"], source_label=source["source_label"],
                    source_statement=source["source_statement"], statement=statement,
                    category=str(benefit_payload.get("category") or "OPERATIONAL_EFFICIENCY").upper(),
                    measure_type=measure_type, formula=formula, assumptions=assumptions,
                    confidence=str(benefit_payload.get("confidence") or "MEDIUM").upper(),
                    approval_state="PENDING", ai_suggestion_id=suggestion.id, created_by=user.id,
                ))
                applied["benefits"] = int(applied["benefits"]) + 1

        elif suggestion.purpose == "DEMO_PLAN":
            if content.get("verification_status") != "PASSED" or not content.get("accept_allowed", False):
                raise HTTPException(409, "This demo plan contains unsupported claims or priority conflicts and cannot be accepted. Refine or regenerate it first.")
            source_revision = content.get("source_report_revision")
            if source_revision is not None and int(source_revision) != report.revision:
                raise HTTPException(409, "The report changed after this demo plan was generated. Generate a new plan before accepting it.")
            plan = content.get("demo_plan")
            if not isinstance(plan, dict) or not plan.get("flow"):
                raise HTTPException(409, "The AI suggestion does not contain a usable demo plan.")
            for current in db.scalars(select(DemoPlanVersion).where(DemoPlanVersion.report_id == report.id, DemoPlanVersion.is_current.is_(True))).all():
                current.is_current = False
            db.add(DemoPlanVersion(
                report_id=report.id, version=_next_demo_plan_version(db, report.id),
                content=plan, source_type="AI_ACCEPTED", source_refs=content.get("source_refs") or [],
                ai_suggestion_id=suggestion.id, is_current=True, created_by=user.id,
            ))
            applied["demo_plan"] = True

        elif suggestion.purpose == "EXECUTIVE_SUMMARY":
            if content.get("verification_status") != "PASSED" or not content.get("accept_allowed", False):
                raise HTTPException(409, "This executive summary contains unsupported claims and cannot be accepted. Refine or regenerate it first.")
            source_revision = content.get("source_report_revision")
            if source_revision is not None and int(source_revision) != report.revision:
                raise HTTPException(409, "The report changed after this executive summary was generated. Generate a new summary before accepting it.")
            summary_text = str(content.get("summary_text") or content.get("suggested_text") or "").strip()
            if not summary_text:
                raise HTTPException(409, "The AI suggestion does not contain a usable executive summary.")
            for current in db.scalars(select(ReportContentVersion).where(ReportContentVersion.report_id == report.id, ReportContentVersion.content_type == "EXECUTIVE_SUMMARY", ReportContentVersion.is_current.is_(True))).all():
                current.is_current = False
            db.add(ReportContentVersion(
                report_id=report.id, content_type="EXECUTIVE_SUMMARY", version=_next_report_content_version(db, report.id, "EXECUTIVE_SUMMARY"),
                text=summary_text, source_type="AI_ACCEPTED", source_refs=content.get("source_refs") or [], ai_suggestion_id=suggestion.id,
                is_current=True, created_by=user.id,
            ))
            applied["executive_summary"] = True

        elif suggested_text and target_section and suggestion.purpose in {"NARRATIVE", "ATTACHMENT_REVIEW"}:
            if suggested_text not in target_section.narrative:
                target_section.narrative = f"{target_section.narrative.strip()}\n\n{suggested_text}".strip()
                sync_narrative_findings(db, report_id=report.id, section=target_section, actor_user_id=user.id)
                target_section.version += 1
                target_section.updated_by = user.id
                applied["narrative"] = True

        for recommendation in content.get("capability_recommendations") or []:
            if not isinstance(recommendation, dict):
                continue
            capability_id = recommendation.get("capability_id") or recommendation.get("id")
            finding_id = recommendation.get("finding_id")
            capability = db.get(Capability, capability_id) if capability_id else None
            finding = db.get(Finding, finding_id) if finding_id else None
            if not capability or capability.status != "APPROVED" or not finding or finding.report_id != report.id:
                continue
            existing = db.scalar(
                select(CapabilityMapping).where(
                    CapabilityMapping.finding_id == finding.id,
                    CapabilityMapping.capability_id == capability.id,
                )
            )
            if existing:
                continue
            db.add(
                CapabilityMapping(
                    report_id=report.id,
                    section_id=finding.section_id,
                    finding_id=finding.id,
                    source_ref=f"finding:{finding.id}",
                    source_type="FINDING",
                    source_label=finding.finding_type.replace("_", " ").title(),
                    source_statement=finding.statement,
                    capability_id=capability.id,
                    rationale=str(recommendation.get("rationale") or recommendation.get("reason") or "AI-assisted recommendation approved by reviewer."),
                    prerequisites=str(recommendation.get("prerequisites") or "") or None,
                    approval_state="APPROVED",
                    approved_by=user.id,
                    ai_suggestion_id=suggestion.id,
                    created_by=user.id,
                )
            )
            applied["mappings"] = int(applied["mappings"]) + 1
        for benefit_item in ([] if suggestion.purpose == "TARGETED_BENEFITS" else (content.get("benefit_statements") or [])):
            benefit_payload = benefit_item if isinstance(benefit_item, dict) else {"statement": str(benefit_item)}
            statement = str(benefit_payload.get("statement") or benefit_payload.get("text") or "").strip()
            if not statement:
                continue
            finding_id = benefit_payload.get("finding_id")
            finding = db.get(Finding, finding_id) if finding_id else None
            if finding and finding.report_id != report.id:
                finding = None
            exists = db.scalar(select(Benefit.id).where(Benefit.report_id == report.id, Benefit.statement == statement))
            if exists:
                continue
            db.add(
                Benefit(
                    report_id=report.id,
                    finding_id=finding.id if finding else None,
                    statement=statement,
                    measure_type=str(benefit_payload.get("measure_type") or "QUALITATIVE").upper(),
                    formula=benefit_payload.get("formula"),
                    assumptions=benefit_payload.get("assumptions"),
                    approval_state="APPROVED",
                    created_by=user.id,
                )
            )
            applied["benefits"] = int(applied["benefits"]) + 1
        content["_applied"] = True
        content["_applied_by"] = user.id
        content["_applied_at"] = _iso(utcnow())
        suggestion.content = content
        _increment_report(report)

    db.add(
        Approval(
            report_id=report.id,
            section_id=suggestion.section_id,
            target_type="AI_SUGGESTION",
            target_id=suggestion.id,
            target_version=1,
            decision=payload.decision,
            decided_by=user.id,
            note=payload.note,
        )
    )
    audit(
        db,
        actor=user,
        action="AI_SUGGESTION_REVIEWED",
        target_type="AI_SUGGESTION",
        target_id=suggestion.id,
        prospect_id=report.prospect_id,
        metadata={"decision": payload.decision, "applied": applied, "purpose": suggestion.purpose},
    )
    db.commit()
    return {"ok": True, "applied": applied}


@router.get("/admin/knowledge")
def list_knowledge(approval_state: str | None = None, process_module: str | None = None, prospect_id: str | None = None, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    stmt = select(KnowledgeEntry).order_by(KnowledgeEntry.updated_at.desc())
    if approval_state:
        stmt = stmt.where(KnowledgeEntry.approval_state == approval_state.upper())
    if process_module:
        stmt = stmt.where(KnowledgeEntry.process_module == process_module)
    if prospect_id:
        stmt = stmt.where(KnowledgeEntry.prospect_id == prospect_id)
    items = list(db.scalars(stmt.limit(500)).all())
    return [{"id": item.id, "source_type": item.source_type, "source_ref": item.source_ref, "source_version": item.source_version, "knowledge_kind": item.knowledge_kind, "structured_data": item.structured_data or {}, "title": item.title, "process_module": item.process_module, "content": item.content, "capability_id": item.capability_id, "prospect_id": item.prospect_id, "classification": item.classification, "reusable_across_prospects": item.reusable_across_prospects, "approval_state": item.approval_state, "approved_by": item.approved_by, "review_due_at": _iso(item.review_due_at), "expires_at": _iso(item.expires_at), "last_reviewed_at": _iso(item.last_reviewed_at), "created_at": _iso(item.created_at), "updated_at": _iso(item.updated_at)} for item in items]


@router.post("/admin/knowledge", dependencies=[Depends(require_csrf)])
def create_knowledge(payload: KnowledgeEntryCreate, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if payload.capability_id and not db.get(Capability, payload.capability_id):
        raise HTTPException(400, "Capability not found.")
    if payload.prospect_id and not db.get(Prospect, payload.prospect_id):
        raise HTTPException(400, "Prospect not found.")
    if payload.reusable_across_prospects and payload.prospect_id:
        raise HTTPException(400, "Prospect-specific entries must be reviewed and de-identified before they can be reusable across prospects.")
    item = KnowledgeEntry(**payload.model_dump(), approval_state="PENDING", created_by=actor.id)
    db.add(item)
    db.flush()
    audit(db, actor=actor, action="KNOWLEDGE_CREATED", target_type="KNOWLEDGE_ENTRY", target_id=item.id, prospect_id=item.prospect_id)
    db.commit()
    return {"id": item.id, "approval_state": item.approval_state}



@router.post("/admin/knowledge/import-configuration", dependencies=[Depends(require_csrf)])
async def import_configuration_knowledge(
    file: UploadFile = File(...),
    actor: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Import Guided Setup JSON/ZIP as product configuration knowledge.

    This endpoint never creates PromptDefinition records and therefore cannot
    change the discovery question library. Imported records are PENDING until
    an administrator/product reviewer approves them.
    """
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "Configuration knowledge file exceeds the configured upload limit.")
    filename = Path(file.filename or "configuration-knowledge.json").name
    try:
        template = load_configuration_template(data, filename)
        records = normalize_configuration_template(template, source_name=filename)
    except (ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, f"Configuration knowledge import failed: {exc}") from exc

    capability_lookup = {
        item.capability_code: item
        for item in db.scalars(select(Capability).order_by(Capability.capability_code)).all()
    }
    created_ids: list[str] = []
    skipped = 0
    newer_versions = 0
    for record in records:
        existing = db.scalar(select(KnowledgeEntry).where(KnowledgeEntry.source_ref == record.source_ref))
        source_ref = record.source_ref
        structured_data = dict(record.structured_data)
        if existing:
            if existing.source_version == record.source_version:
                skipped += 1
                continue
            source_ref = f"{record.source_ref}:v{record.source_version}"
            if db.scalar(select(KnowledgeEntry.id).where(KnowledgeEntry.source_ref == source_ref)):
                skipped += 1
                continue
            structured_data["supersedes_entry_id"] = existing.id
            newer_versions += 1
        capability = capability_lookup.get(record.capability_code or "")
        item = KnowledgeEntry(
            source_type=CONFIGURATION_SOURCE_TYPE,
            source_ref=source_ref,
            source_version=record.source_version,
            knowledge_kind=CONFIGURATION_KNOWLEDGE_KIND,
            structured_data=structured_data,
            title=record.title,
            process_module=record.process_module,
            content=record.content,
            capability_id=capability.id if capability else None,
            prospect_id=None,
            classification="INTERNAL",
            reusable_across_prospects=True,
            approval_state="PENDING",
            created_by=actor.id,
        )
        db.add(item)
        db.flush()
        created_ids.append(item.id)
    audit(
        db,
        actor=actor,
        action="CONFIGURATION_KNOWLEDGE_IMPORTED",
        target_type="KNOWLEDGE_IMPORT",
        target_id=hashlib.sha256(data).hexdigest()[:20],
        metadata={
            "file_name": filename,
            "source_version": str((template.get("_meta") or {}).get("version") or "unknown"),
            "records_found": len(records),
            "created": len(created_ids),
            "newer_versions": newer_versions,
            "skipped": skipped,
            "discovery_prompts_created": 0,
        },
    )
    db.commit()
    return {
        "source_version": str((template.get("_meta") or {}).get("version") or "unknown"),
        "records_found": len(records),
        "created": len(created_ids),
        "newer_versions": newer_versions,
        "skipped": skipped,
        "approval_state": "PENDING",
        "discovery_prompts_created": 0,
    }


@router.post("/admin/knowledge/import", dependencies=[Depends(require_csrf)])
async def import_knowledge_document(
    title: str = Form(...),
    process_module: str | None = Form(None),
    capability_id: str | None = Form(None),
    prospect_id: str | None = Form(None),
    file: UploadFile = File(...),
    actor: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    clean_title = title.strip()
    if len(clean_title) < 2:
        raise HTTPException(400, "Knowledge document title is required.")
    capability = db.get(Capability, capability_id) if capability_id else None
    if capability_id and not capability:
        raise HTTPException(400, "Linked capability was not found.")
    prospect = db.get(Prospect, prospect_id) if prospect_id else None
    if prospect_id and not prospect:
        raise HTTPException(400, "Prospect was not found.")

    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "Knowledge document exceeds the configured upload limit.")
    filename = Path(file.filename or "historical-document").name
    extraction = extract_text(data, filename, file.content_type)
    if extraction.state != "COMPLETED" or not extraction.text:
        reason = extraction.reason or f"Extraction state: {extraction.state}"
        raise HTTPException(400, f"The historical document could not be converted to reusable text. {reason}")

    chunks = _knowledge_chunks(extraction.text)
    if not chunks:
        raise HTTPException(400, "No reusable text was extracted from the historical document.")
    digest = hashlib.sha256(data).hexdigest()
    module_key = (process_module or "general").strip().lower().replace(" ", "_")[:60] or "general"
    created_ids: list[str] = []
    skipped = 0
    for index, chunk in enumerate(chunks, start=1):
        source_ref = f"historical:{digest[:20]}:{module_key}:{index:03d}"
        if db.scalar(select(KnowledgeEntry.id).where(KnowledgeEntry.source_ref == source_ref)):
            skipped += 1
            continue
        item = KnowledgeEntry(
            source_type="HISTORICAL_DOCUMENT",
            source_ref=source_ref,
            title=clean_title if len(chunks) == 1 else f"{clean_title} — Part {index} of {len(chunks)}",
            process_module=(process_module or "").strip() or None,
            content=chunk,
            capability_id=capability.id if capability else None,
            prospect_id=prospect.id if prospect else None,
            classification="CONFIDENTIAL" if prospect else "INTERNAL",
            reusable_across_prospects=False,
            approval_state="PENDING",
            created_by=actor.id,
        )
        db.add(item)
        db.flush()
        created_ids.append(item.id)
    audit(
        db,
        actor=actor,
        action="KNOWLEDGE_DOCUMENT_IMPORTED",
        target_type="KNOWLEDGE_IMPORT",
        target_id=digest[:20],
        prospect_id=prospect.id if prospect else None,
        metadata={
            "title": clean_title,
            "file_name": filename,
            "sha256": digest,
            "chunks_created": len(created_ids),
            "chunks_skipped": skipped,
            "process_module": process_module,
            "capability_id": capability_id,
        },
    )
    db.commit()
    return {
        "created": len(created_ids),
        "skipped": skipped,
        "entry_ids": created_ids,
        "extraction_state": extraction.state,
        "classification": "CONFIDENTIAL" if prospect else "INTERNAL",
        "message": "Historical knowledge imported as pending review. It will not ground AI output until approved.",
    }


@router.post("/admin/knowledge/{entry_id}/review", dependencies=[Depends(require_csrf)])
def review_knowledge(entry_id: str, payload: KnowledgeEntryReview, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    item = db.get(KnowledgeEntry, entry_id)
    if not item:
        raise HTTPException(404, "Knowledge entry not found.")
    if payload.title is not None:
        item.title = payload.title
    if payload.content is not None:
        item.content = payload.content
    reusable = payload.reusable_across_prospects if payload.reusable_across_prospects is not None else item.reusable_across_prospects
    if reusable and item.prospect_id:
        prospect = db.get(Prospect, item.prospect_id)
        if payload.content is None:
            raise HTTPException(400, "A de-identified replacement content value is required before a prospect-specific entry can become reusable.")
        if prospect and prospect.name.lower() in payload.content.lower():
            raise HTTPException(400, "De-identified reusable knowledge cannot contain the prospect name.")
        item.prospect_id = None
        item.classification = "INTERNAL"
    item.reusable_across_prospects = reusable
    if payload.review_due_at is not None:
        item.review_due_at = payload.review_due_at
    if payload.expires_at is not None:
        item.expires_at = payload.expires_at
    if payload.decision == "APPROVED" and item.knowledge_kind == CONFIGURATION_KNOWLEDGE_KIND:
        supersedes_id = str((item.structured_data or {}).get("supersedes_entry_id") or "")
        if supersedes_id:
            prior = db.get(KnowledgeEntry, supersedes_id)
            if prior and prior.knowledge_kind == CONFIGURATION_KNOWLEDGE_KIND and prior.approval_state == "APPROVED":
                prior.approval_state = "SUPERSEDED"
                prior.last_reviewed_at = utcnow()
                prior.last_reviewed_by = actor.id
    item.approval_state = payload.decision
    item.approved_by = actor.id if payload.decision == "APPROVED" else None
    item.last_reviewed_at = utcnow()
    item.last_reviewed_by = actor.id
    audit(db, actor=actor, action="KNOWLEDGE_REVIEWED", target_type="KNOWLEDGE_ENTRY", target_id=item.id, prospect_id=item.prospect_id, metadata={"decision": payload.decision, "reusable": item.reusable_across_prospects, "note": payload.note})
    db.commit()
    return {"ok": True, "approval_state": item.approval_state, "reusable_across_prospects": item.reusable_across_prospects}


@router.get("/admin/review-queue")
def admin_review_queue(actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    return calculate_admin_review_queue(db)


@router.get("/admin/operations")
def admin_operations(actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return calculate_admin_operations(db, settings)


@router.get("/admin/branding")
def get_branding(actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    brand = db.scalar(select(BrandingProfile).where(BrandingProfile.is_default.is_(True), BrandingProfile.active.is_(True)).order_by(BrandingProfile.version.desc()))
    if not brand:
        raise HTTPException(404, "Default branding not found.")
    return {
        "id": brand.id, "name": brand.name, "version": brand.version,
        "primary_color": brand.primary_color, "secondary_color": brand.secondary_color,
        "accent_color": brand.accent_color, "heading_font": brand.heading_font,
        "body_font": brand.body_font, "confidentiality_text": brand.confidentiality_text,
        "draft_watermark": brand.draft_watermark, "footer_text": brand.footer_text,
        "photo_size_uom": brand.photo_size_uom,
        "landscape_photo_width": brand.landscape_photo_width,
        "landscape_photo_height": brand.landscape_photo_height,
        "portrait_photo_width": brand.portrait_photo_width,
        "portrait_photo_height": brand.portrait_photo_height,
        "has_custom_logo": bool(brand.logo_storage_key),
    }


@router.patch("/admin/branding/{brand_id}", dependencies=[Depends(require_csrf)])
def update_branding(brand_id: str, payload: BrandingUpdate, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    brand = db.get(BrandingProfile, brand_id)
    if not brand:
        raise HTTPException(404, "Branding profile not found.")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(brand, key, value)
    audit(db, actor=actor, action="BRANDING_UPDATED", target_type="BRANDING_PROFILE", target_id=brand.id, metadata={"fields": sorted(data)})
    db.commit()
    return {"ok": True}


@router.post("/admin/branding/{brand_id}/logo", dependencies=[Depends(require_csrf)])
async def upload_branding_logo(brand_id: str, file: UploadFile = File(...), actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    brand = db.get(BrandingProfile, brand_id)
    if not brand:
        raise HTTPException(404, "Branding profile not found.")
    data = await file.read(min(settings.max_upload_bytes, 10_485_760) + 1)
    if len(data) > min(settings.max_upload_bytes, 10_485_760):
        raise HTTPException(413, "Logo exceeds the 10 MB limit.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1600, 800), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            logo_bytes = output.getvalue()
    except Exception:
        raise HTTPException(400, "The uploaded logo could not be decoded as an image.")
    storage = _object_storage_or_503(settings)
    old_key = brand.logo_storage_key
    key = f"branding/{brand.id}/{uuid.uuid4().hex}/logo.png"
    stored = storage.put_bytes(key, logo_bytes, "image/png")
    brand.logo_storage_key = stored.key
    if old_key:
        try:
            storage.delete(old_key)
        except FileNotFoundError:
            pass
    audit(db, actor=actor, action="BRANDING_LOGO_UPDATED", target_type="BRANDING_PROFILE", target_id=brand.id, metadata={"file_name": safe_filename(file.filename or "logo.png"), "size": stored.size})
    db.commit()
    return {"ok": True, "has_custom_logo": True}


@router.get("/admin/audit")
def get_audit(limit: int = 100, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(max(limit, 1), 500))).all())
    return [{"id": e.id, "actor_user_id": e.actor_user_id, "prospect_id": e.prospect_id, "action": e.action, "target_type": e.target_type, "target_id": e.target_id, "metadata": e.event_metadata, "created_at": _iso(e.created_at)} for e in events]
