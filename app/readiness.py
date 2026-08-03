from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import (
    AiJob,
    AiSuggestion,
    Benefit,
    Capability,
    CapabilityMapping,
    Comment,
    DemoPlanVersion,
    DemoSectionPriority,
    Job,
    KnowledgeEntry,
    Publication,
    Report,
    ReportContentVersion,
    ReportSection,
    Response,
    Finding,
    SectionContentVersion,
    WorkerHeartbeat,
)
from .storage import storage_configuration_status


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _latest_quality_suggestion(db: Session, report_id: str) -> AiSuggestion | None:
    return db.scalar(
        select(AiSuggestion)
        .where(AiSuggestion.report_id == report_id, AiSuggestion.purpose == "REPORT_QUALITY_REVIEW")
        .order_by(AiSuggestion.created_at.desc())
    )


def _current_report_content(db: Session, report_id: str, content_type: str) -> ReportContentVersion | None:
    return db.scalar(
        select(ReportContentVersion)
        .where(
            ReportContentVersion.report_id == report_id,
            ReportContentVersion.content_type == content_type,
            ReportContentVersion.is_current.is_(True),
        )
        .order_by(ReportContentVersion.version.desc())
    )


def calculate_report_readiness(db: Session, report: Report) -> dict[str, Any]:
    sections = list(
        db.scalars(
            select(ReportSection)
            .where(ReportSection.report_id == report.id, ReportSection.state != "REMOVED")
            .order_by(ReportSection.display_order)
        ).all()
    )
    findings = list(db.scalars(select(Finding).where(Finding.report_id == report.id, Finding.status != "REJECTED")).all())
    responses = list(db.scalars(select(Response).where(Response.report_id == report.id)).all())
    approaches = list(
        db.scalars(
            select(SectionContentVersion).where(
                SectionContentVersion.report_id == report.id,
                SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH",
                SectionContentVersion.is_current.is_(True),
            )
        ).all()
    )
    mappings = list(db.scalars(select(CapabilityMapping).where(CapabilityMapping.report_id == report.id)).all())
    benefits = list(db.scalars(select(Benefit).where(Benefit.report_id == report.id)).all())
    priorities = list(db.scalars(select(DemoSectionPriority).where(DemoSectionPriority.report_id == report.id)).all())
    demo_plan = db.scalar(
        select(DemoPlanVersion)
        .where(DemoPlanVersion.report_id == report.id, DemoPlanVersion.is_current.is_(True))
        .order_by(DemoPlanVersion.version.desc())
    )
    demo_section_ids = {
        str(item.get("section_id"))
        for item in ((demo_plan.content or {}).get("flow") if demo_plan else []) or []
        if item.get("section_id")
    }

    responses_by_section = Counter(item.section_id for item in responses if (item.narrative or "").strip() or item.payload)
    findings_by_section = Counter(item.section_id for item in findings if item.section_id)
    approach_by_section = {item.section_id: item for item in approaches}
    approved_mappings = Counter(item.section_id for item in mappings if item.section_id and item.approval_state == "APPROVED")
    pending_mappings = Counter(item.section_id for item in mappings if item.section_id and item.approval_state == "PENDING")
    approved_benefits = Counter(item.section_id for item in benefits if item.section_id and item.approval_state == "APPROVED")
    pending_benefits = Counter(item.section_id for item in benefits if item.section_id and item.approval_state == "PENDING")
    priority_by_section = {item.section_id: item for item in priorities}

    rows: list[dict[str, Any]] = []
    for section in sections:
        current_operations = bool(section.narrative.strip() or responses_by_section[section.id] or findings_by_section[section.id])
        operational = bool(section.process_module)
        priority = priority_by_section.get(section.id)
        demo_priority = priority.priority if priority else "OPTIONAL"
        demo_required = demo_priority in {"MUST_SHOW", "SHOULD_SHOW"}
        demo_covered = section.id in demo_section_ids or demo_priority == "DO_NOT_SHOW"
        approach_present = section.id in approach_by_section and bool(approach_by_section[section.id].text.strip())
        mapping_count = approved_mappings[section.id]
        benefit_count = approved_benefits[section.id]
        review_required = bool(pending_mappings[section.id] or pending_benefits[section.id])

        if not operational:
            status = "NOT_APPLICABLE"
        elif not current_operations:
            status = "MISSING"
        elif review_required:
            status = "REVIEW_REQUIRED"
        elif approach_present and mapping_count and benefit_count and (not demo_required or demo_covered):
            status = "READY"
        else:
            status = "PARTIAL"

        missing: list[str] = []
        if operational and not current_operations:
            missing.append("Current operations")
        if operational and current_operations and not approach_present:
            missing.append("Cloud Inventory approach")
        if operational and current_operations and not mapping_count:
            missing.append("Approved functionality mapping")
        if operational and current_operations and not benefit_count:
            missing.append("Approved targeted benefit")
        if operational and demo_required and not demo_covered:
            missing.append("Accepted demo-plan coverage")

        rows.append(
            {
                "section_id": section.id,
                "title": section.title,
                "process_module": section.process_module,
                "status": status,
                "current_operations": current_operations,
                "finding_count": findings_by_section[section.id],
                "approach_present": approach_present,
                "approved_mapping_count": mapping_count,
                "pending_mapping_count": pending_mappings[section.id],
                "approved_benefit_count": benefit_count,
                "pending_benefit_count": pending_benefits[section.id],
                "demo_priority": demo_priority,
                "demo_covered": demo_covered,
                "missing": missing,
            }
        )

    counts = Counter(row["status"] for row in rows)
    operational_rows = [row for row in rows if row["status"] != "NOT_APPLICABLE"]
    if operational_rows and all(row["status"] == "READY" for row in operational_rows):
        overall = "READY"
    elif any(row["status"] == "REVIEW_REQUIRED" for row in operational_rows):
        overall = "REVIEW_REQUIRED"
    elif any(row["status"] == "MISSING" for row in operational_rows):
        overall = "MISSING"
    else:
        overall = "PARTIAL"

    summary = _current_report_content(db, report.id, "EXECUTIVE_SUMMARY")
    return {
        "overall_status": overall,
        "report_revision": report.revision,
        "counts": dict(counts),
        "sections": rows,
        "executive_summary_present": bool(summary and summary.text.strip()),
        "demo_plan_present": demo_plan is not None,
    }


def _is_stale_suggestion(db: Session, report: Report, suggestion: AiSuggestion) -> bool:
    content = suggestion.content or {}
    report_revision = content.get("source_report_revision")
    if report_revision is not None and int(report_revision) != report.revision:
        return True
    section_version = content.get("source_section_version")
    if section_version is not None and suggestion.section_id:
        section = db.get(ReportSection, suggestion.section_id)
        return section is None or int(section_version) != section.version
    return False


def calculate_review_queue(db: Session, report: Report) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    sections = {item.id: item for item in db.scalars(select(ReportSection).where(ReportSection.report_id == report.id)).all()}

    for mapping in db.scalars(select(CapabilityMapping).where(CapabilityMapping.report_id == report.id, CapabilityMapping.approval_state == "PENDING")).all():
        items.append({"type": "CAPABILITY_MAPPING", "id": mapping.id, "section_id": mapping.section_id, "section_title": sections.get(mapping.section_id).title if mapping.section_id in sections else None, "label": mapping.source_label or "Capability mapping", "status": "PENDING"})
    for benefit in db.scalars(select(Benefit).where(Benefit.report_id == report.id, Benefit.approval_state == "PENDING")).all():
        items.append({"type": "BENEFIT", "id": benefit.id, "section_id": benefit.section_id, "section_title": sections.get(benefit.section_id).title if benefit.section_id in sections else None, "label": benefit.statement, "status": "PENDING"})
    for suggestion in db.scalars(select(AiSuggestion).where(AiSuggestion.report_id == report.id, AiSuggestion.review_state == "PENDING").order_by(AiSuggestion.created_at.desc())).all():
        items.append({"type": "AI_SUGGESTION", "id": suggestion.id, "section_id": suggestion.section_id, "section_title": sections.get(suggestion.section_id).title if suggestion.section_id in sections else None, "label": suggestion.purpose.replace("_", " ").title(), "status": "STALE" if _is_stale_suggestion(db, report, suggestion) else "PENDING"})
    for comment in db.scalars(select(Comment).where(Comment.report_id == report.id, Comment.status == "OPEN").order_by(Comment.created_at)).all():
        items.append({"type": "COMMENT", "id": comment.id, "section_id": comment.section_id, "section_title": sections.get(comment.section_id).title if comment.section_id in sections else None, "label": comment.body, "status": "OPEN"})
    for publication in db.scalars(select(Publication).where(Publication.report_id == report.id, Publication.status == "FAILED", Publication.dismissed_at.is_(None)).order_by(Publication.created_at.desc())).all():
        items.append({"type": "PUBLICATION", "id": publication.id, "section_id": None, "section_title": None, "label": publication.publication_type.replace("_", " ").title(), "status": "FAILED"})

    quality = _latest_quality_suggestion(db, report.id)
    quality_issues = ((quality.content or {}).get("issues") if quality and quality.review_state == "PENDING" else []) or []
    for index, issue in enumerate(quality_issues):
        items.append({
            "type": "QUALITY_ISSUE",
            "id": f"{quality.id}:{index}",
            "section_id": issue.get("section_id"),
            "section_title": issue.get("section_title"),
            "label": issue.get("message") or issue.get("recommendation") or "Report quality issue",
            "status": issue.get("severity") or "WARNING",
            "category": issue.get("category"),
        })

    counts = Counter(item["type"] for item in items)
    return {"count": len(items), "counts": dict(counts), "items": items}


def calculate_traceability(db: Session, report: Report) -> dict[str, Any]:
    sections = list(db.scalars(select(ReportSection).where(ReportSection.report_id == report.id, ReportSection.state != "REMOVED").order_by(ReportSection.display_order)).all())
    mappings = list(db.scalars(select(CapabilityMapping).where(CapabilityMapping.report_id == report.id, CapabilityMapping.approval_state == "APPROVED")).all())
    benefits = list(db.scalars(select(Benefit).where(Benefit.report_id == report.id, Benefit.approval_state == "APPROVED")).all())
    approaches = list(db.scalars(select(SectionContentVersion).where(SectionContentVersion.report_id == report.id, SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH", SectionContentVersion.is_current.is_(True))).all())
    approach_by_section = {item.section_id: item for item in approaches}

    rows = []
    for section in sections:
        claims: list[dict[str, Any]] = []
        if section.narrative.strip():
            claims.append({"classification": "DIRECT_OBSERVATION", "text": section.narrative, "source_refs": ["section:narrative"]})
        approach = approach_by_section.get(section.id)
        if approach and approach.text.strip():
            classification = "APPROVED_PRODUCT_STATEMENT" if approach.source_type == "AI_ACCEPTED" else "USER_INTERPRETATION"
            claims.append({"classification": classification, "text": approach.text, "source_refs": approach.source_refs})
        for mapping in [item for item in mappings if item.section_id == section.id]:
            claims.append({"classification": "APPROVED_PRODUCT_STATEMENT", "text": mapping.rationale, "source_refs": [mapping.source_ref] if mapping.source_ref else []})
        for benefit in [item for item in benefits if item.section_id == section.id]:
            classification = "SUPPORTED_QUANTITATIVE_CLAIM" if benefit.measure_type == "QUANTITATIVE" else "EXPECTED_QUALITATIVE_BENEFIT"
            claims.append({"classification": classification, "text": benefit.statement, "source_refs": [benefit.source_ref] if benefit.source_ref else []})
        rows.append({"section_id": section.id, "section_title": section.title, "claims": claims})

    summary = _current_report_content(db, report.id, "EXECUTIVE_SUMMARY")
    return {
        "sections": rows,
        "executive_summary": None if not summary else {
            "text": summary.text,
            "classification": "USER_INTERPRETATION",
            "source_refs": summary.source_refs,
        },
    }


def calculate_admin_review_queue(db: Session) -> dict[str, Any]:
    reports = {item.id: item for item in db.scalars(select(Report)).all()}
    items: list[dict[str, Any]] = []
    for report in reports.values():
        queue = calculate_review_queue(db, report)
        for item in queue["items"]:
            items.append({**item, "report_id": report.id, "report_title": report.title, "prospect_id": report.prospect_id})
    for entry in db.scalars(select(KnowledgeEntry).where(KnowledgeEntry.approval_state == "PENDING").order_by(KnowledgeEntry.created_at)).all():
        items.append({"type": "KNOWLEDGE", "id": entry.id, "label": entry.title, "status": "PENDING", "report_id": None, "report_title": None, "prospect_id": entry.prospect_id})
    counts = Counter(item["type"] for item in items)
    return {"count": len(items), "counts": dict(counts), "items": items}


def calculate_admin_operations(db: Session, settings: Settings) -> dict[str, Any]:
    ai_counts = dict(db.execute(select(AiJob.status, func.count(AiJob.id)).group_by(AiJob.status)).all())
    job_counts = dict(db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all())
    ai_jobs = list(db.scalars(select(AiJob).where(AiJob.completed_at.is_not(None)).order_by(AiJob.completed_at.desc()).limit(250)).all())
    durations = [max(0.0, (item.completed_at - item.created_at).total_seconds()) for item in ai_jobs if item.completed_at]
    tokens = Counter()
    for item in ai_jobs:
        usage = item.token_usage or {}
        for key in ("input_tokens", "output_tokens", "total_tokens", "calls"):
            value = usage.get(key)
            if isinstance(value, int):
                tokens[key] += value
    heartbeat = db.get(WorkerHeartbeat, "worker")
    last_publication = db.scalar(select(Publication).where(Publication.status == "COMPLETED").order_by(Publication.completed_at.desc()))
    recent_failures = list(db.scalars(select(AiJob).where(AiJob.status.in_(["FAILED", "BLOCKED"])).order_by(AiJob.created_at.desc()).limit(10)).all())
    now = datetime.now(timezone.utc)
    heartbeat_age = None
    if heartbeat:
        last_seen = heartbeat.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        heartbeat_age = max(0.0, (now - last_seen).total_seconds())
    due_capabilities = db.scalar(select(func.count(Capability.id)).where(Capability.review_due_at.is_not(None), Capability.review_due_at <= now)) or 0
    due_knowledge = db.scalar(select(func.count(KnowledgeEntry.id)).where(KnowledgeEntry.review_due_at.is_not(None), KnowledgeEntry.review_due_at <= now)) or 0
    expired_knowledge = db.scalar(select(func.count(KnowledgeEntry.id)).where(KnowledgeEntry.expires_at.is_not(None), KnowledgeEntry.expires_at <= now)) or 0
    return {
        "app_version": settings.app_version,
        "ai": {
            "enabled": settings.ai_enabled,
            "model": settings.openai_model,
            "job_counts": ai_counts,
            "average_processing_seconds": round(sum(durations) / len(durations), 2) if durations else None,
            "token_usage": dict(tokens),
            "recent_failures": [{"id": item.id, "purpose": item.purpose, "error": item.error, "created_at": _iso(item.created_at)} for item in recent_failures],
        },
        "queue": {"job_counts": job_counts},
        "worker": None if not heartbeat else {
            "status": heartbeat.status,
            "app_version": heartbeat.app_version,
            "storage_configured": heartbeat.storage_configured,
            "last_seen_at": _iso(heartbeat.last_seen_at),
            "age_seconds": heartbeat_age,
            "details": heartbeat.details,
        },
        "storage": storage_configuration_status(settings),
        "last_successful_publication": None if not last_publication else {"id": last_publication.id, "report_id": last_publication.report_id, "publication_type": last_publication.publication_type, "completed_at": _iso(last_publication.completed_at)},
        "lifecycle": {"capabilities_due": int(due_capabilities), "knowledge_due": int(due_knowledge), "knowledge_expired": int(expired_knowledge)},
    }
