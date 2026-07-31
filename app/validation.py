from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AiSuggestion,
    Benefit,
    CapabilityMapping,
    Comment,
    EvidenceItem,
    Finding,
    PromptDefinition,
    Report,
    ReportSection,
    Response,
)

_PLACEHOLDER = re.compile(r"(?:\bTBD\b|\bTODO\b|\[insert|describe the benefits|placeholder)", re.IGNORECASE)


def validate_report(db: Session, report: Report, final_requested: bool) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    def add(code: str, severity: str, message: str, *, section_id: str | None = None, target_id: str | None = None) -> None:
        issues.append({"code": code, "severity": severity, "message": message, "section_id": section_id, "target_id": target_id})

    if report.merged_into_report_id:
        add("REPORT_MERGED", "ERROR", "This source report has already been merged and cannot be published.")
    if report.state == "DELETED":
        add("REPORT_DELETED", "ERROR", "Deleted reports cannot be published.")

    sections = list(db.scalars(select(ReportSection).where(ReportSection.report_id == report.id).order_by(ReportSection.display_order)).all())
    active_sections = [s for s in sections if s.state != "REMOVED"]
    if not active_sections:
        add("NO_ACTIVE_SECTIONS", "ERROR", "The report has no active sections.")

    for section in active_sections:
        response_count = db.scalar(select(func.count(Response.id)).where(Response.section_id == section.id)) or 0
        has_content = bool(section.narrative.strip()) or response_count > 0
        if section.required_on_final and not has_content:
            add("REQUIRED_SECTION_EMPTY", "ERROR" if final_requested else "WARNING", f"Required section '{section.title}' has no captured content.", section_id=section.id)
        elif not has_content:
            add("SECTION_EMPTY", "WARNING", f"Section '{section.title}' has no captured content.", section_id=section.id)
        if _PLACEHOLDER.search(section.narrative or ""):
            add("PLACEHOLDER_TEXT", "ERROR" if final_requested else "WARNING", f"Section '{section.title}' contains placeholder text.", section_id=section.id)
        if final_requested and section.state not in {"APPROVED", "READY_FOR_REVIEW"}:
            add("SECTION_NOT_REVIEWED", "ERROR", f"Section '{section.title}' has not reached review/approval state.", section_id=section.id)

        # Prompt-level validation is intentionally quiet for untouched draft sections. It becomes
        # mandatory for final generation, or once a contributor has started the section.
        if final_requested or has_content:
            required_prompts = list(db.scalars(select(PromptDefinition).where(
                PromptDefinition.active.is_(True),
                PromptDefinition.required_on_final.is_(True),
                (PromptDefinition.process_module == section.process_module) if section.process_module else PromptDefinition.process_module.is_(None),
            )).all())
            answered = set(db.scalars(select(Response.prompt_id).where(Response.section_id == section.id)).all())
            for prompt in required_prompts:
                if prompt.id not in answered:
                    add("REQUIRED_PROMPT_UNANSWERED", "ERROR" if final_requested else "WARNING", f"Required question is unanswered: {prompt.question}", section_id=section.id, target_id=prompt.id)

    evidence = list(db.scalars(select(EvidenceItem).where(EvidenceItem.report_id == report.id)).all())
    for item in evidence:
        if item.status not in {"READY", "AVAILABLE"}:
            add("EVIDENCE_NOT_READY", "ERROR" if final_requested else "WARNING", "An evidence item is not ready for publication.", section_id=item.section_id, target_id=item.id)
        if not (item.caption or "").strip():
            add("EVIDENCE_MISSING_CAPTION", "WARNING", "An evidence item has no caption.", section_id=item.section_id, target_id=item.id)
        if item.extraction_state == "FAILED":
            add("EVIDENCE_EXTRACTION_FAILED", "WARNING", "Text extraction failed for a supporting attachment; review it manually.", section_id=item.section_id, target_id=item.id)

    open_comments = db.scalar(select(func.count(Comment.id)).where(Comment.report_id == report.id, Comment.status == "OPEN")) or 0
    if open_comments:
        add("COMMENTS_OPEN", "ERROR" if final_requested else "WARNING", f"{open_comments} collaboration comment(s) remain unresolved.")

    pending_ai = db.scalar(select(func.count(AiSuggestion.id)).where(AiSuggestion.report_id == report.id, AiSuggestion.review_state == "PENDING")) or 0
    if pending_ai:
        add("AI_SUGGESTIONS_PENDING", "ERROR" if final_requested else "WARNING", f"{pending_ai} AI suggestion(s) still require human review.")

    pending_mappings = db.scalar(select(func.count(CapabilityMapping.id)).where(CapabilityMapping.report_id == report.id, CapabilityMapping.approval_state == "PENDING")) or 0
    if pending_mappings:
        add("CAPABILITY_MAPPINGS_PENDING", "ERROR" if final_requested else "WARNING", f"{pending_mappings} capability mapping(s) require approval.")

    pending_benefits = db.scalar(select(func.count(Benefit.id)).where(Benefit.report_id == report.id, Benefit.approval_state == "PENDING")) or 0
    if pending_benefits:
        add("BENEFITS_PENDING", "ERROR" if final_requested else "WARNING", f"{pending_benefits} benefit statement(s) require approval.")

    findings = list(db.scalars(select(Finding).where(Finding.report_id == report.id, Finding.status != "REJECTED")).all())
    for finding in findings:
        mapped = db.scalar(select(func.count(CapabilityMapping.id)).where(CapabilityMapping.finding_id == finding.id)) or 0
        if finding.finding_type in {"PAIN_POINT", "RISK", "GAP"} and not mapped:
            add("FINDING_UNADDRESSED", "WARNING", "A pain point or gap has no mapped Cloud Inventory capability.", section_id=finding.section_id, target_id=finding.id)

    return issues


def validation_passed(issues: list[dict[str, Any]]) -> bool:
    return not any(issue["severity"] == "ERROR" for issue in issues)
