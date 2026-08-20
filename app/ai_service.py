from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import Settings
from .audit import audit
from .models import AiJob, AiSuggestion, Capability, EvidenceItem, Finding, KnowledgeEntry, PromptDefinition, Report, ReportSection, Response, User, utcnow


@dataclass
class AiPolicyDecision:
    allowed: bool
    reason: str
    mode: str

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason, "mode": self.mode}


def evaluate_policy(settings: Settings, *, contains_prospect_confidential_content: bool = True) -> AiPolicyDecision:
    if not settings.ai_enabled:
        return AiPolicyDecision(False, "AI is disabled by configuration.", "disabled")
    if not settings.openai_api_key:
        return AiPolicyDecision(False, "OPENAI_API_KEY is not configured.", "missing-key")
    if contains_prospect_confidential_content:
        if not settings.ai_confidential_content_enabled:
            return AiPolicyDecision(False, "Confidential AI processing is disabled.", "confidential-disabled")
        if settings.openai_data_control_mode != "zero_data_retention":
            return AiPolicyDecision(False, "Prospect-confidential content requires approved Zero Data Retention configuration.", "zdr-required")
    return AiPolicyDecision(True, "Policy checks passed.", settings.openai_data_control_mode)


def build_context(db: Session, report: Report, section: ReportSection | None, purpose: str, instructions: str | None) -> dict[str, Any]:
    sections = [section] if section else list(db.scalars(select(ReportSection).where(ReportSection.report_id == report.id, ReportSection.state != "REMOVED").order_by(ReportSection.display_order)).all())
    section_payload = []
    for sec in sections:
        responses = db.execute(
            select(Response, PromptDefinition).join(PromptDefinition, Response.prompt_id == PromptDefinition.id).where(Response.section_id == sec.id)
        ).all()
        section_payload.append({
            "id": sec.id,
            "title": sec.title,
            "process_module": sec.process_module,
            "narrative": sec.narrative,
            "responses": [{"question": prompt.question, "answer": response.narrative, "payload": response.payload} for response, prompt in responses],
        })
    findings = list(db.scalars(select(Finding).where(Finding.report_id == report.id)).all())
    evidence_stmt = select(EvidenceItem).where(EvidenceItem.report_id == report.id, EvidenceItem.extracted_text.is_not(None))
    if section:
        evidence_stmt = evidence_stmt.where(EvidenceItem.section_id == section.id)
    evidence = list(db.scalars(evidence_stmt.order_by(EvidenceItem.created_at)).all())
    capabilities = list(db.scalars(select(Capability).where(Capability.status == "APPROVED").order_by(Capability.domain, Capability.name)).all())
    knowledge = list(db.scalars(
        select(KnowledgeEntry).where(
            KnowledgeEntry.approval_state == "APPROVED",
            or_(
                KnowledgeEntry.prospect_id == report.prospect_id,
                KnowledgeEntry.reusable_across_prospects.is_(True),
            ),
        ).order_by(KnowledgeEntry.process_module, KnowledgeEntry.title).limit(250)
    ).all())
    return {
        "purpose": purpose,
        "instructions": instructions,
        "report": {"id": report.id, "title": report.title, "revision": report.revision},
        "sections": section_payload,
        "findings": [{"id": f.id, "type": f.finding_type, "statement": f.statement, "impact": f.impact, "confidence": f.confidence} for f in findings],
        "extracted_evidence": [{"id": e.id, "section_id": e.section_id, "caption": e.caption, "classification": e.classification, "text": (e.extracted_text or "")[:20000]} for e in evidence],
        "approved_knowledge": [{"id": k.id, "title": k.title, "process_module": k.process_module, "content": k.content, "source_type": k.source_type, "source_ref": k.source_ref, "prospect_specific": k.prospect_id is not None} for k in knowledge],
        "approved_capability_catalog": [{"id": c.id, "code": c.capability_code, "name": c.name, "domain": c.domain, "description": c.controlled_description, "prerequisites": c.typical_prerequisites, "limitations": c.limitations} for c in capabilities],
    }


def run_ai(settings: Settings, context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    # Imported lazily so non-AI deployments and tests do not require the SDK at process startup.
    from openai import OpenAI  # type: ignore

    client_kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
    if settings.openai_project_id:
        client_kwargs["project"] = settings.openai_project_id
    client = OpenAI(**client_kwargs)
    system = (
        "You are an internal Cloud Inventory discovery-report assistant. Use only evidence supplied in the input and the approved capability catalog. "
        "Do not invent customer facts, performance numbers, product capabilities, or guarantees. Separate facts, assumptions, gaps, and recommendations. "
        "Return JSON with keys: summary, suggested_text, gaps, follow_up_questions, capability_recommendations, benefit_statements, source_refs. "
        "Every capability recommendation must reference an approved capability id. All output is a draft requiring human approval."
    )
    response = client.responses.create(
        model=settings.openai_model,
        store=False,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
    )
    text = getattr(response, "output_text", "") or ""
    try:
        content = json.loads(text)
    except json.JSONDecodeError:
        content = {"summary": "", "suggested_text": text, "gaps": [], "follow_up_questions": [], "capability_recommendations": [], "benefit_statements": [], "source_refs": []}
    usage_obj = getattr(response, "usage", None)
    usage = usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else {}
    return content, usage


def process_ai_job(db: Session, ai_job_id: str, settings: Settings) -> AiSuggestion:
    job = db.get(AiJob, ai_job_id)
    if not job:
        raise ValueError("AI job not found")
    if job.status == "BLOCKED":
        raise ValueError("AI job is blocked by policy")
    existing = db.scalar(select(AiSuggestion).where(AiSuggestion.ai_job_id == job.id).order_by(AiSuggestion.created_at.desc()))
    if existing and job.status == "COMPLETED":
        return existing
    report = db.get(Report, job.report_id)
    if not report:
        raise ValueError("Report not found")
    section = db.get(ReportSection, job.section_id) if job.section_id else None
    if section and section.report_id != report.id:
        raise ValueError("AI job section does not belong to report")
    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    if not decision.allowed:
        job.status = "BLOCKED"
        job.policy_decision = decision.as_dict()
        job.error = decision.reason
        job.completed_at = utcnow()
        db.commit()
        raise ValueError(decision.reason)
    job.status = "RUNNING"
    job.error = None
    db.commit()
    try:
        context = build_context(db, report, section, job.purpose, job.instructions)
        content, usage = run_ai(settings, context)
        suggestion = db.scalar(select(AiSuggestion).where(AiSuggestion.ai_job_id == job.id).order_by(AiSuggestion.created_at.desc()))
        if not suggestion:
            suggestion = AiSuggestion(
                ai_job_id=job.id,
                report_id=report.id,
                section_id=job.section_id,
                purpose=job.purpose,
                content=content,
                source_refs=content.get("source_refs", []),
                confidence="MEDIUM",
                review_state="PENDING",
            )
            db.add(suggestion)
            db.flush()
        else:
            suggestion.content = content
            suggestion.source_refs = content.get("source_refs", [])
        job.status = "COMPLETED"
        job.token_usage = usage
        job.completed_at = utcnow()
        actor = db.get(User, job.requested_by)
        audit(db, actor=actor, action="AI_SUGGESTION_CREATED", target_type="AI_SUGGESTION", target_id=suggestion.id, prospect_id=report.prospect_id, metadata={"purpose": job.purpose, "ai_job_id": job.id})
        db.commit()
        db.refresh(suggestion)
        return suggestion
    except Exception as exc:
        job.status = "FAILED"
        job.error = str(exc)[:10000]
        job.completed_at = utcnow()
        db.commit()
        raise
