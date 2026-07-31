from __future__ import annotations

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
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .access import accessible_prospect_ids, require_prospect_access, require_report_access
from .ai_service import evaluate_policy
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
    ReportMember,
    ReportSection,
    ReportTemplate,
    Response,
    SectionTemplate,
    Site,
    User,
    UserRole,
    ValidationRun,
    utcnow,
)
from .schemas import (
    AiRequest,
    BenefitCreate,
    BrandingUpdate,
    CapabilityCreate,
    CapabilityMappingCreate,
    CapabilityUpdate,
    CommentCreate,
    EngagementCreate,
    EvidenceReviewRequest,
    FindingCreate,
    LoginRequest,
    KnowledgeEntryCreate,
    KnowledgeEntryReview,
    MergeRequest,
    MetricCreate,
    PasswordChangeRequest,
    ProspectArchiveRequest,
    ProspectCreate,
    ProspectOnboardingCreate,
    ProspectDeleteRequest,
    PublicationRequest,
    QuickCaptureRequest,
    ReportCreate,
    ReportDeleteRequest,
    ResponseUpsert,
    ReviewDecision,
    SectionCreate,
    SectionUpdate,
    SiteCreate,
    UserCreate,
    ValidationRequest,
)
from .storage import ObjectStorage, build_storage_key, safe_filename
from .validation import validate_report, validation_passed

router = APIRouter(prefix="/api")


def _iso(value):
    return value.isoformat() if value else None


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


def _create_knowledge_candidates(db: Session, report: Report, actor: User) -> int:
    """Capture approved report knowledge without making it cross-prospect reusable.

    The admin knowledge-review workflow is the only way to de-identify and promote a candidate
    for use across prospects. This prevents accidental leakage of customer-confidential content.
    """
    created = 0
    mappings = db.execute(
        select(CapabilityMapping, Capability, Finding)
        .join(Capability, CapabilityMapping.capability_id == Capability.id)
        .join(Finding, CapabilityMapping.finding_id == Finding.id)
        .where(CapabilityMapping.report_id == report.id, CapabilityMapping.approval_state == "APPROVED")
    ).all()
    for mapping, capability, finding in mappings:
        source_ref = f"report:{report.id}:mapping:{mapping.id}"
        if db.scalar(select(KnowledgeEntry.id).where(KnowledgeEntry.source_ref == source_ref)):
            continue
        content = (
            f"Observed issue: {finding.statement}\n"
            f"Impact: {finding.impact or 'Not stated'}\n"
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
    # Any authenticated user can see names for collaboration; sensitive security fields are excluded.
    users = list(db.scalars(select(User).where(User.status != "DELETED").order_by(User.display_name, User.username)).all())
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "email": u.email, "status": u.status, "roles": sorted(user_roles(db, u.id))} for u in users]


@router.post("/admin/users", dependencies=[Depends(require_csrf)])
def create_user(payload: UserCreate, actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(or_(User.username == payload.username, User.email == str(payload.email)))):
        raise HTTPException(status_code=409, detail="Username or email already exists.")
    new_user = User(username=payload.username, email=str(payload.email), display_name=payload.display_name, password_hash=hash_password(payload.password), force_password_change=True)
    db.add(new_user)
    db.flush()
    for role in set(payload.roles):
        db.add(UserRole(user_id=new_user.id, role=role.upper()))
    audit(db, actor=actor, action="USER_CREATED", target_type="USER", target_id=new_user.id, metadata={"roles": payload.roles})
    db.commit()
    return _user_payload(db, new_user)


@router.get("/prospects")
def list_prospects(user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    ids = accessible_prospect_ids(db, user)
    stmt = select(Prospect).where(Prospect.status != "DELETED").order_by(Prospect.updated_at.desc())
    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(Prospect.id.in_(ids))
    prospects = list(db.scalars(stmt).all())
    return [{"id": p.id, "name": p.name, "industry": p.industry, "opportunity": p.opportunity, "status": p.status, "retention_due_at": _iso(p.retention_due_at), "archive_prompted_at": _iso(p.archive_prompted_at), "last_exported_at": _iso(p.last_exported_at), "legal_hold": p.legal_hold, "updated_at": _iso(p.updated_at)} for p in prospects]


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
        "prospect": {"id": prospect.id, "name": prospect.name, "industry": prospect.industry, "opportunity": prospect.opportunity, "status": prospect.status, "retention_due_at": _iso(prospect.retention_due_at), "archive_prompted_at": _iso(prospect.archive_prompted_at), "last_exported_at": _iso(prospect.last_exported_at), "legal_hold": prospect.legal_hold},
        "access_scope": scope,
        "sites": [{"id": s.id, "name": s.name, "address": s.address, "timezone": s.timezone} for s in sites],
        "engagements": [{"id": e.id, "name": e.name, "site_id": e.site_id, "survey_date": _iso(e.survey_date), "status": e.status, "owner_id": e.owner_id} for e in engagements],
        "reports": [{"id": r.id, "title": r.title, "state": r.state, "report_kind": r.report_kind, "owner_id": r.owner_id, "revision": r.revision, "updated_at": _iso(r.updated_at), "merged_into_report_id": r.merged_into_report_id} for r in reports],
        "members": [{"user_id": u.id, "display_name": u.display_name or u.username, "email": u.email, "role_scope": m.role_scope} for m, u in members],
    }


@router.get("/prospects/{prospect_id}/export")
def export_prospect(prospect_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    prospect = db.get(Prospect, prospect_id)
    if not prospect:
        raise HTTPException(404, "Prospect not found.")
    require_prospect_access(db, user, prospect_id, "OWNER")
    storage = ObjectStorage(settings)
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
    storage = ObjectStorage(settings)
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


@router.get("/reports/{report_id}")
def get_report(report_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    scope = require_report_access(db, user, report)
    sections = list(db.scalars(select(ReportSection).where(ReportSection.report_id == report.id).order_by(ReportSection.display_order)).all())
    responses = db.execute(select(Response, PromptDefinition).join(PromptDefinition, Response.prompt_id == PromptDefinition.id).where(Response.report_id == report.id)).all()
    response_map: dict[str, list[dict[str, Any]]] = {}
    for response, prompt in responses:
        response_map.setdefault(response.section_id, []).append({"id": response.id, "prompt_id": prompt.id, "question": prompt.question, "answer_type": prompt.answer_type, "narrative": response.narrative, "payload": response.payload, "version": response.version})
    findings = list(db.scalars(select(Finding).where(Finding.report_id == report.id).order_by(Finding.created_at)).all())
    metrics = list(db.scalars(select(Metric).where(Metric.report_id == report.id).order_by(Metric.created_at)).all())
    evidence = db.execute(select(EvidenceItem, FileObject).join(FileObject, FileObject.evidence_id == EvidenceItem.id, isouter=True).where(EvidenceItem.report_id == report.id).order_by(EvidenceItem.created_at)).all()
    capabilities = db.execute(select(CapabilityMapping, Capability).join(Capability, CapabilityMapping.capability_id == Capability.id).where(CapabilityMapping.report_id == report.id)).all()
    benefits = list(db.scalars(select(Benefit).where(Benefit.report_id == report.id).order_by(Benefit.created_at)).all())
    suggestions = list(db.scalars(select(AiSuggestion).where(AiSuggestion.report_id == report.id).order_by(AiSuggestion.created_at.desc())).all())
    publications = list(db.scalars(select(Publication).where(Publication.report_id == report.id).order_by(Publication.created_at.desc())).all())
    comments = db.execute(select(Comment, User).join(User, Comment.author_id == User.id).where(Comment.report_id == report.id).order_by(Comment.created_at)).all()
    members = db.execute(select(ReportMember, User).join(User, ReportMember.user_id == User.id).where(ReportMember.report_id == report.id)).all()
    prompt_defs = list(db.scalars(select(PromptDefinition).where(PromptDefinition.active.is_(True)).order_by(PromptDefinition.process_module, PromptDefinition.display_order)).all())
    prompts_by_module: dict[str, list[dict[str, Any]]] = {}
    for p in prompt_defs:
        prompts_by_module.setdefault(p.process_module or "GENERAL", []).append({"id": p.id, "stable_key": p.stable_key, "question": p.question, "answer_type": p.answer_type, "required_on_final": p.required_on_final, "mobile_priority": p.mobile_priority})
    return {
        "report": {"id": report.id, "prospect_id": report.prospect_id, "engagement_id": report.engagement_id, "site_id": report.site_id, "title": report.title, "report_kind": report.report_kind, "state": report.state, "revision": report.revision, "owner_id": report.owner_id, "updated_at": _iso(report.updated_at)},
        "access_scope": scope,
        "sections": [{"id": s.id, "stable_key": s.stable_key, "title": s.title, "process_module": s.process_module, "display_order": s.display_order, "state": s.state, "required_on_final": s.required_on_final, "removed_reason": s.removed_reason, "narrative": s.narrative, "version": s.version, "assigned_to_user_id": s.assigned_to_user_id, "responses": response_map.get(s.id, [])} for s in sections],
        "prompts_by_module": prompts_by_module,
        "findings": [{"id": f.id, "section_id": f.section_id, "finding_type": f.finding_type, "statement": f.statement, "impact": f.impact, "confidence": f.confidence, "status": f.status} for f in findings],
        "metrics": [{"id": m.id, "section_id": m.section_id, "name": m.name, "value_numeric": m.value_numeric, "value_text": m.value_text, "unit": m.unit, "period": m.period, "source": m.source, "confidence": m.confidence} for m in metrics],
        "evidence": [{"id": e.id, "section_id": e.section_id, "evidence_type": e.evidence_type, "caption": e.caption, "placement": e.placement, "classification": e.classification, "status": e.status, "extraction_state": e.extraction_state, "has_extracted_text": bool(e.extracted_text), "ai_inclusion_recommendation": e.ai_inclusion_recommendation, "file": {"id": f.id, "file_name": f.file_name, "mime_type": f.mime_type, "size_bytes": f.size_bytes, "variant": f.variant} if f else None} for e, f in evidence if not f or f.variant == "ORIGINAL"],
        "capability_mappings": [{"id": m.id, "finding_id": m.finding_id, "capability_id": c.id, "capability_code": c.capability_code, "capability_name": c.name, "rationale": m.rationale, "prerequisites": m.prerequisites, "approval_state": m.approval_state} for m, c in capabilities],
        "benefits": [{"id": b.id, "finding_id": b.finding_id, "capability_mapping_id": b.capability_mapping_id, "statement": b.statement, "measure_type": b.measure_type, "formula": b.formula, "assumptions": b.assumptions, "approval_state": b.approval_state} for b in benefits],
        "ai_suggestions": [{"id": s.id, "section_id": s.section_id, "purpose": s.purpose, "content": s.content, "confidence": s.confidence, "review_state": s.review_state, "created_at": _iso(s.created_at)} for s in suggestions],
        "publications": [{"id": p.id, "publication_type": p.publication_type, "is_final": p.is_final, "status": p.status, "docx_file_id": p.docx_file_id, "pdf_file_id": p.pdf_file_id, "error": p.error, "created_at": _iso(p.created_at)} for p in publications],
        "members": [{"user_id": member.user_id, "role_scope": member.role_scope, "display_name": member_user.display_name, "username": member_user.username} for member, member_user in members],
        "comments": [{"id": comment.id, "section_id": comment.section_id, "author_id": comment.author_id, "author_name": comment_user.display_name or comment_user.username, "body": comment.body, "status": comment.status, "created_at": _iso(comment.created_at), "resolved_at": _iso(comment.resolved_at)} for comment, comment_user in comments],
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
    section = ReportSection(report_id=report.id, stable_key=stable, title=payload.title, process_module=payload.process_module, display_order=max_order + 10, required_on_final=payload.required_on_final, created_by=user.id, updated_by=user.id)
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
    if "assigned_to_user_id" in data and data["assigned_to_user_id"] is not None:
        if data["assigned_to_user_id"] not in _report_member_user_ids(db, report):
            raise HTTPException(400, "Section can only be assigned to a report member.")
    for key, value in data.items():
        setattr(section, key, value)
    section.version += 1
    section.updated_by = user.id
    _increment_report(report)
    audit(db, actor=user, action="REPORT_SECTION_UPDATED", target_type="REPORT_SECTION", target_id=section.id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "fields": sorted(data)})
    db.commit()
    return {"ok": True, "version": section.version, "report_revision": report.revision}


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
    section.state = "IN_PROGRESS" if section.state == "NOT_STARTED" else section.state
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
            return {"id": existing.id, "deduplicated": True}
    finding = Finding(report_id=report.id, section_id=section.id, finding_type=payload.finding_type, statement=payload.note, impact=payload.impact, confidence=payload.confidence, client_mutation_id=payload.client_mutation_id, created_by=user.id)
    db.add(finding)
    section.state = "IN_PROGRESS" if section.state == "NOT_STARTED" else section.state
    section.updated_by = user.id
    section.version += 1
    _increment_report(report)
    audit(db, actor=user, action="QUICK_CAPTURE_CREATED", target_type="FINDING", target_id=finding.id, prospect_id=report.prospect_id, metadata={"report_id": report.id, "section_id": section.id})
    db.commit()
    return {"id": finding.id, "report_revision": report.revision}


@router.post("/reports/{report_id}/findings", dependencies=[Depends(require_csrf)])
def create_finding(report_id: str, payload: FindingCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    if payload.section_id:
        section = _get_section(db, payload.section_id)
        if section.report_id != report.id:
            raise HTTPException(400, "Section does not belong to report.")
    finding = Finding(report_id=report.id, section_id=payload.section_id, finding_type=payload.finding_type, statement=payload.statement, impact=payload.impact, confidence=payload.confidence, client_mutation_id=payload.client_mutation_id, created_by=user.id)
    db.add(finding)
    _increment_report(report)
    audit(db, actor=user, action="FINDING_CREATED", target_type="FINDING", target_id=finding.id, prospect_id=report.prospect_id, metadata={"report_id": report.id})
    db.commit()
    return {"id": finding.id}


@router.post("/reports/{report_id}/metrics", dependencies=[Depends(require_csrf)])
def create_metric(report_id: str, payload: MetricCreate, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    metric = Metric(report_id=report.id, section_id=payload.section_id, created_by=user.id, **payload.model_dump(exclude={"section_id"}))
    db.add(metric)
    _increment_report(report)
    audit(db, actor=user, action="METRIC_CREATED", target_type="METRIC", target_id=metric.id, prospect_id=report.prospect_id, metadata={"report_id": report.id})
    db.commit()
    return {"id": metric.id}


@router.get("/capabilities")
def list_capabilities(domain: str | None = None, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    stmt = select(Capability).where(Capability.status != "RETIRED").order_by(Capability.domain, Capability.name)
    if domain:
        stmt = stmt.where(Capability.domain == domain)
    items = list(db.scalars(stmt).all())
    return [{"id": c.id, "capability_code": c.capability_code, "name": c.name, "domain": c.domain, "controlled_description": c.controlled_description, "typical_prerequisites": c.typical_prerequisites, "limitations": c.limitations, "status": c.status, "source": c.source, "version": c.version} for c in items]


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
    finding = db.get(Finding, payload.finding_id)
    capability = db.get(Capability, payload.capability_id)
    if not finding or finding.report_id != report.id or not capability:
        raise HTTPException(400, "Invalid finding or capability.")
    if capability.status != "APPROVED":
        raise HTTPException(409, "Only approved capabilities can be mapped to prospect findings.")
    mapping = CapabilityMapping(report_id=report.id, finding_id=finding.id, capability_id=capability.id, rationale=payload.rationale, prerequisites=payload.prerequisites, created_by=user.id)
    db.add(mapping)
    _increment_report(report)
    audit(db, actor=user, action="CAPABILITY_MAPPING_CREATED", target_type="CAPABILITY_MAPPING", target_id=mapping.id, prospect_id=report.prospect_id, metadata={"report_id": report.id})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This capability is already mapped to the finding.")
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
    benefit = Benefit(report_id=report.id, created_by=user.id, **payload.model_dump())
    db.add(benefit)
    _increment_report(report)
    audit(db, actor=user, action="BENEFIT_CREATED", target_type="BENEFIT", target_id=benefit.id, prospect_id=report.prospect_id, metadata={"report_id": report.id})
    db.commit()
    return {"id": benefit.id}


@router.post("/reports/{report_id}/benefits/{benefit_id}/review", dependencies=[Depends(require_csrf)])
def review_benefit(report_id: str, benefit_id: str, payload: ReviewDecision, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "REVIEWER")
    benefit = db.get(Benefit, benefit_id)
    if not benefit or benefit.report_id != report.id:
        raise HTTPException(404, "Benefit not found.")
    benefit.approval_state = payload.decision
    db.add(Approval(report_id=report.id, target_type="BENEFIT", target_id=benefit.id, target_version=1, decision=payload.decision, decided_by=user.id, note=payload.note))
    _increment_report(report)
    audit(db, actor=user, action="BENEFIT_REVIEWED", target_type="BENEFIT", target_id=benefit.id, prospect_id=report.prospect_id, metadata={"decision": payload.decision})
    db.commit()
    return {"ok": True}


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
    storage = ObjectStorage(settings)
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
        section.state = "IN_PROGRESS" if section.state == "NOT_STARTED" else section.state
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


@router.get("/files/{file_id}")
def download_file(file_id: str, inline: bool = False, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    file_obj = db.get(FileObject, file_id)
    if not file_obj:
        raise HTTPException(404, "File not found.")
    require_prospect_access(db, user, file_obj.prospect_id)
    storage = ObjectStorage(settings)
    url = storage.signed_download_url(file_obj.storage_key, file_obj.file_name, file_obj.mime_type)
    if url:
        return RedirectResponse(url)
    data = storage.get_bytes(file_obj.storage_key)
    disposition = "inline" if inline else "attachment"
    return StreamingResponse(io.BytesIO(data), media_type=file_obj.mime_type, headers={"Content-Disposition": f'{disposition}; filename="{safe_filename(file_obj.file_name)}"'})


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
    enqueue(db, "publication.generate", {"publication_id": publication.id})
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
    return {"id": publication.id, "status": publication.status, "publication_type": publication.publication_type, "is_final": publication.is_final, "docx_file_id": publication.docx_file_id, "pdf_file_id": publication.pdf_file_id, "error": publication.error, "completed_at": _iso(publication.completed_at)}


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
    storage = ObjectStorage(settings)
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
    storage = ObjectStorage(settings)
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
            target_section.version += 1
            db.add(MergeLineage(merge_operation_id=operation.id, target_type="REPORT_SECTION", target_id=target_section.id, source_report_id=source.id, source_type="REPORT_SECTION", source_id=source_section.id, source_version=source_section.version))
            for finding in db.scalars(select(Finding).where(Finding.report_id == source.id, Finding.section_id == source_section.id)).all():
                clone = Finding(report_id=target.id, section_id=target_section.id, finding_type=finding.finding_type, statement=finding.statement, impact=finding.impact, confidence=finding.confidence, status=finding.status, created_by=finding.created_by)
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


@router.post("/reports/{report_id}/ai", dependencies=[Depends(require_csrf)], status_code=status.HTTP_202_ACCEPTED)
def request_ai(report_id: str, payload: AiRequest, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report)
    section = db.get(ReportSection, payload.section_id) if payload.section_id else None
    if section and section.report_id != report.id:
        raise HTTPException(400, "Section does not belong to report.")
    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    job = AiJob(
        report_id=report.id,
        section_id=payload.section_id,
        purpose=payload.purpose,
        instructions=payload.instructions,
        model=settings.openai_model,
        policy_decision=decision.as_dict(),
        status="BLOCKED" if not decision.allowed else "QUEUED",
        requested_by=user.id,
    )
    db.add(job)
    db.flush()
    if not decision.allowed:
        audit(db, actor=user, action="AI_REQUEST_BLOCKED", target_type="AI_JOB", target_id=job.id, prospect_id=report.prospect_id, metadata=decision.as_dict())
        db.commit()
        raise HTTPException(status_code=403, detail={"message": decision.reason, "ai_job_id": job.id, "policy": decision.as_dict()})
    enqueue(db, "ai.generate", {"ai_job_id": job.id}, max_attempts=3)
    audit(db, actor=user, action="AI_REQUEST_QUEUED", target_type="AI_JOB", target_id=job.id, prospect_id=report.prospect_id, metadata={"purpose": payload.purpose})
    db.commit()
    return {"ai_job_id": job.id, "status": job.status, "message": "AI draft queued for generation and human review."}


@router.get("/ai-jobs/{ai_job_id}")
def get_ai_job(ai_job_id: str, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    job = db.get(AiJob, ai_job_id)
    if not job:
        raise HTTPException(404, "AI job not found.")
    report = _get_report(db, job.report_id)
    require_report_access(db, user, report)
    suggestion = db.scalar(select(AiSuggestion).where(AiSuggestion.ai_job_id == job.id).order_by(AiSuggestion.created_at.desc()))
    return {
        "id": job.id,
        "report_id": job.report_id,
        "section_id": job.section_id,
        "purpose": job.purpose,
        "status": job.status,
        "model": job.model,
        "policy_decision": job.policy_decision,
        "token_usage": job.token_usage,
        "error": job.error,
        "created_at": _iso(job.created_at),
        "completed_at": _iso(job.completed_at),
        "suggestion": None if not suggestion else {
            "id": suggestion.id,
            "content": suggestion.content,
            "source_refs": suggestion.source_refs,
            "confidence": suggestion.confidence,
            "review_state": suggestion.review_state,
            "created_at": _iso(suggestion.created_at),
        },
    }


@router.post("/reports/{report_id}/ai-suggestions/{suggestion_id}/review", dependencies=[Depends(require_csrf)])
def review_ai(report_id: str, suggestion_id: str, payload: ReviewDecision, user: User = Depends(enforce_password_changed), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    require_report_access(db, user, report, "REVIEWER")
    suggestion = db.get(AiSuggestion, suggestion_id)
    if not suggestion or suggestion.report_id != report.id:
        raise HTTPException(404, "Suggestion not found.")
    suggestion.review_state = payload.decision
    suggestion.reviewed_by = user.id
    suggestion.review_note = payload.note
    suggestion.reviewed_at = utcnow()
    applied: dict[str, int | bool] = {"narrative": False, "mappings": 0, "benefits": 0}
    content = dict(suggestion.content or {})
    if payload.decision == "APPROVED" and not content.get("_applied"):
        target_section = db.get(ReportSection, suggestion.section_id) if suggestion.section_id else None
        suggested_text = str(content.get("suggested_text") or content.get("summary") or "").strip()
        if suggested_text and target_section and suggestion.purpose in {"NARRATIVE", "EXECUTIVE_SUMMARY", "ATTACHMENT_REVIEW"}:
            if suggested_text not in target_section.narrative:
                target_section.narrative = f"{target_section.narrative.strip()}\n\n{suggested_text}".strip()
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
            existing = db.scalar(select(CapabilityMapping).where(CapabilityMapping.finding_id == finding.id, CapabilityMapping.capability_id == capability.id))
            if existing:
                continue
            db.add(CapabilityMapping(
                report_id=report.id, finding_id=finding.id, capability_id=capability.id,
                rationale=str(recommendation.get("rationale") or recommendation.get("reason") or "AI-assisted recommendation approved by reviewer."),
                prerequisites=str(recommendation.get("prerequisites") or "") or None,
                approval_state="APPROVED", approved_by=user.id, created_by=user.id,
            ))
            applied["mappings"] = int(applied["mappings"]) + 1
        for benefit_item in content.get("benefit_statements") or []:
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
            db.add(Benefit(
                report_id=report.id, finding_id=finding.id if finding else None,
                statement=statement,
                measure_type=str(benefit_payload.get("measure_type") or "QUALITATIVE").upper(),
                formula=benefit_payload.get("formula"), assumptions=benefit_payload.get("assumptions"),
                approval_state="APPROVED", created_by=user.id,
            ))
            applied["benefits"] = int(applied["benefits"]) + 1
        content["_applied"] = True
        content["_applied_by"] = user.id
        content["_applied_at"] = _iso(utcnow())
        suggestion.content = content
        _increment_report(report)
    db.add(Approval(report_id=report.id, section_id=suggestion.section_id, target_type="AI_SUGGESTION", target_id=suggestion.id, target_version=1, decision=payload.decision, decided_by=user.id, note=payload.note))
    audit(db, actor=user, action="AI_SUGGESTION_REVIEWED", target_type="AI_SUGGESTION", target_id=suggestion.id, prospect_id=report.prospect_id, metadata={"decision": payload.decision, "applied": applied})
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
    return [{"id": item.id, "source_type": item.source_type, "source_ref": item.source_ref, "title": item.title, "process_module": item.process_module, "content": item.content, "capability_id": item.capability_id, "prospect_id": item.prospect_id, "classification": item.classification, "reusable_across_prospects": item.reusable_across_prospects, "approval_state": item.approval_state, "approved_by": item.approved_by, "created_at": _iso(item.created_at), "updated_at": _iso(item.updated_at)} for item in items]


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
    item.approval_state = payload.decision
    item.approved_by = actor.id if payload.decision == "APPROVED" else None
    audit(db, actor=actor, action="KNOWLEDGE_REVIEWED", target_type="KNOWLEDGE_ENTRY", target_id=item.id, prospect_id=item.prospect_id, metadata={"decision": payload.decision, "reusable": item.reusable_across_prospects, "note": payload.note})
    db.commit()
    return {"ok": True, "approval_state": item.approval_state, "reusable_across_prospects": item.reusable_across_prospects}


@router.get("/admin/branding")
def get_branding(actor: User = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)):
    brand = db.scalar(select(BrandingProfile).where(BrandingProfile.is_default.is_(True), BrandingProfile.active.is_(True)).order_by(BrandingProfile.version.desc()))
    if not brand:
        raise HTTPException(404, "Default branding not found.")
    return {"id": brand.id, "name": brand.name, "version": brand.version, "primary_color": brand.primary_color, "secondary_color": brand.secondary_color, "accent_color": brand.accent_color, "heading_font": brand.heading_font, "body_font": brand.body_font, "confidentiality_text": brand.confidentiality_text, "draft_watermark": brand.draft_watermark, "footer_text": brand.footer_text, "has_custom_logo": bool(brand.logo_storage_key)}


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
    storage = ObjectStorage(settings)
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
