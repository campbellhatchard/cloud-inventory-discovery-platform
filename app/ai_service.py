from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .audit import audit
from .config import Settings
from .models import (
    AiJob,
    AiSuggestion,
    Benefit,
    Capability,
    CapabilityMapping,
    DemoPlanSettings,
    DemoPlanVersion,
    DemoSectionPriority,
    EvidenceAiObservation,
    EvidenceItem,
    FileObject,
    Finding,
    KnowledgeEntry,
    Metric,
    PromptDefinition,
    Report,
    ReportContentVersion,
    ReportSection,
    Response,
    SectionContentVersion,
    User,
    utcnow,
)
from .storage import ObjectStorage


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
    sections = [section] if section else list(
        db.scalars(
            select(ReportSection)
            .where(ReportSection.report_id == report.id, ReportSection.state != "REMOVED")
            .order_by(ReportSection.display_order)
        ).all()
    )
    section_payload = []
    for sec in sections:
        responses = db.execute(
            select(Response, PromptDefinition)
            .join(PromptDefinition, Response.prompt_id == PromptDefinition.id)
            .where(Response.section_id == sec.id)
        ).all()
        section_payload.append(
            {
                "id": sec.id,
                "title": sec.title,
                "process_module": sec.process_module,
                "narrative": sec.narrative,
                "responses": [
                    {"question": prompt.question, "answer": response.narrative, "payload": response.payload}
                    for response, prompt in responses
                ],
            }
        )
    findings = list(db.scalars(select(Finding).where(Finding.report_id == report.id)).all())
    evidence_stmt = select(EvidenceItem).where(EvidenceItem.report_id == report.id, EvidenceItem.extracted_text.is_not(None))
    if section:
        evidence_stmt = evidence_stmt.where(EvidenceItem.section_id == section.id)
    evidence = list(db.scalars(evidence_stmt.order_by(EvidenceItem.created_at)).all())
    capabilities = list(
        db.scalars(select(Capability).where(Capability.status == "APPROVED").order_by(Capability.domain, Capability.name)).all()
    )
    knowledge = list(
        db.scalars(
            select(KnowledgeEntry)
            .where(
                KnowledgeEntry.approval_state == "APPROVED",
                or_(KnowledgeEntry.expires_at.is_(None), KnowledgeEntry.expires_at > utcnow()),
                or_(KnowledgeEntry.prospect_id == report.prospect_id, KnowledgeEntry.reusable_across_prospects.is_(True)),
            )
            .order_by(KnowledgeEntry.process_module, KnowledgeEntry.title)
            .limit(250)
        ).all()
    )
    return {
        "purpose": purpose,
        "instructions": instructions,
        "report": {"id": report.id, "title": report.title, "revision": report.revision},
        "sections": section_payload,
        "findings": [
            {"id": f.id, "type": f.finding_type, "statement": f.statement, "impact": f.impact, "confidence": f.confidence}
            for f in findings
        ],
        "extracted_evidence": [
            {
                "id": e.id,
                "section_id": e.section_id,
                "caption": e.caption,
                "classification": e.classification,
                "text": (e.extracted_text or "")[:20000],
            }
            for e in evidence
        ],
        "approved_knowledge": [
            {
                "id": k.id,
                "title": k.title,
                "process_module": k.process_module,
                "content": k.content,
                "source_type": k.source_type,
                "source_ref": k.source_ref,
                "prospect_specific": k.prospect_id is not None,
            }
            for k in knowledge
        ],
        "approved_capability_catalog": [
            {
                "id": c.id,
                "code": c.capability_code,
                "name": c.name,
                "domain": c.domain,
                "description": c.controlled_description,
                "prerequisites": c.typical_prerequisites,
                "limitations": c.limitations,
            }
            for c in capabilities
        ],
    }


def build_observation_snapshot(
    db: Session,
    report: Report,
    section: ReportSection,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Capture the exact user-entered source material at request time.

    The snapshot is intentionally limited to current-state observations for the
    selected section. Product capabilities, benefits, and historical knowledge
    are excluded so the enhancement cannot accidentally introduce solution
    claims into a description of the customer's current operation.
    """
    selected_ids = list(dict.fromkeys(evidence_ids or []))
    response_rows = db.execute(
        select(Response, PromptDefinition)
        .join(PromptDefinition, Response.prompt_id == PromptDefinition.id)
        .where(Response.section_id == section.id, PromptDefinition.active.is_(True))
        .order_by(PromptDefinition.display_order)
    ).all()
    findings = list(
        db.scalars(
            select(Finding)
            .where(Finding.report_id == report.id, Finding.section_id == section.id, Finding.status != "REJECTED")
            .order_by(Finding.created_at)
        ).all()
    )
    metrics = list(
        db.scalars(
            select(Metric)
            .where(Metric.report_id == report.id, Metric.section_id == section.id)
            .order_by(Metric.created_at)
        ).all()
    )
    evidence: list[EvidenceItem] = []
    if selected_ids:
        evidence = list(
            db.scalars(
                select(EvidenceItem)
                .where(
                    EvidenceItem.report_id == report.id,
                    EvidenceItem.section_id == section.id,
                    EvidenceItem.id.in_(selected_ids),
                )
                .order_by(EvidenceItem.created_at)
            ).all()
        )
        found_ids = {item.id for item in evidence}
        missing = [item_id for item_id in selected_ids if item_id not in found_ids]
        if missing:
            raise ValueError("One or more selected evidence items are not available in this section.")

    sources: list[dict[str, Any]] = []
    if section.narrative.strip():
        sources.append(
            {
                "ref": "section:narrative",
                "type": "SECTION_NARRATIVE",
                "label": "Section narrative",
                "text": section.narrative.strip(),
            }
        )
    for response, prompt in response_rows:
        if not response.narrative.strip() and not response.payload:
            continue
        sources.append(
            {
                "ref": f"response:{response.id}",
                "type": "GUIDED_RESPONSE",
                "label": prompt.question,
                "text": response.narrative.strip() or json.dumps(response.payload, ensure_ascii=False),
            }
        )
    for finding in findings:
        text = finding.statement.strip()
        if finding.impact:
            text += f"\nImpact noted by user: {finding.impact.strip()}"
        sources.append(
            {
                "ref": f"finding:{finding.id}",
                "type": "FINDING",
                "label": finding.finding_type.replace("_", " ").title(),
                "text": text,
            }
        )
    for metric in metrics:
        value = metric.value_text if metric.value_text is not None else metric.value_numeric
        if value is None:
            continue
        unit = f" {metric.unit}" if metric.unit else ""
        period = f" ({metric.period})" if metric.period else ""
        sources.append(
            {
                "ref": f"metric:{metric.id}",
                "type": "METRIC",
                "label": metric.name,
                "text": f"{metric.name}: {value}{unit}{period}",
            }
        )
    for item in evidence:
        sources.append(
            {
                "ref": f"evidence:{item.id}",
                "type": "PHOTO",
                "label": item.caption or "Section photograph",
                "text": item.caption or "No caption supplied.",
                "evidence_id": item.id,
            }
        )

    return {
        "purpose": "OBSERVATION_ENHANCEMENT",
        "report": {"id": report.id, "title": report.title, "revision": report.revision},
        "section": {
            "id": section.id,
            "title": section.title,
            "process_module": section.process_module,
            "version": section.version,
            "original_narrative": section.narrative,
        },
        "selected_evidence_ids": selected_ids,
        "sources": sources,
    }


def _client(settings: Settings):
    from openai import OpenAI  # type: ignore

    client_kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
    if settings.openai_project_id:
        client_kwargs["project"] = settings.openai_project_id
    return OpenAI(**client_kwargs)


def _usage(response: Any) -> dict[str, Any]:
    usage_obj = getattr(response, "usage", None)
    return usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else {}


def _parse_json(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate
        if candidate.endswith("```"):
            candidate = candidate[:-3]
        candidate = candidate.strip()
        if candidate.lower().startswith("json"):
            candidate = candidate[4:].lstrip()
    try:
        payload = json.loads(candidate)
        return payload if isinstance(payload, dict) else {"value": payload}
    except json.JSONDecodeError:
        return {"enhanced_text": candidate}


def _call_json(
    settings: Settings,
    *,
    system: str,
    user_content: Any,
    reasoning_effort: str | None = None,
    verbosity: str | None = None,
    max_output_tokens: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the Responses API with optional latency-oriented request controls.

    The application keeps the configured model unchanged. Latency-sensitive,
    tightly-bounded tasks can request lower reasoning effort, lower verbosity,
    and a bounded output without changing the model or the data-control policy.
    """
    client = _client(settings)
    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "store": False,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}
    if verbosity:
        kwargs["text"] = {"verbosity": verbosity}
    if max_output_tokens:
        kwargs["max_output_tokens"] = max_output_tokens
    response = client.responses.create(**kwargs)
    return _parse_json(getattr(response, "output_text", "") or ""), _usage(response)


def run_ai(settings: Settings, context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "You are an internal Cloud Inventory discovery-report assistant. Use only evidence supplied in the input and the approved capability catalog. "
        "Do not invent customer facts, performance numbers, product capabilities, or guarantees. Separate facts, assumptions, gaps, and recommendations. "
        "Return JSON with keys: summary, suggested_text, gaps, follow_up_questions, capability_recommendations, benefit_statements, source_refs. "
        "Every capability recommendation must reference an approved capability id. All output is a draft requiring human approval."
    )
    return _call_json(settings, system=system, user_content=json.dumps(context, ensure_ascii=False))


def _image_file(db: Session, evidence_id: str) -> FileObject | None:
    files = list(db.scalars(select(FileObject).where(FileObject.evidence_id == evidence_id)).all())
    images = [item for item in files if item.mime_type.startswith("image/")]
    if not images:
        return None
    images.sort(key=lambda item: (0 if item.variant == "WEB" else 1 if item.variant == "ORIGINAL" else 2, item.created_at))
    return images[0]


def _merge_usage(items: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": len(items)}
    for item in items:
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = item.get(key)
            if isinstance(value, int):
                totals[key] += value
    totals["details"] = items
    return totals


def _photo_observation(
    db: Session,
    settings: Settings,
    evidence: EvidenceItem,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Analyze the image independently of customer narrative or captions.

    A low-detail visual pass is the default. The model may request one high-detail
    pass only when fine visual detail is material to the operational observation.
    Results are cached by image SHA so moving the same photograph between sections
    does not trigger another vision call unless the underlying image changes.
    """
    file_obj = _image_file(db, evidence.id)
    if not file_obj:
        return {
            "visible_observations": [],
            "operational_interpretations": [],
            "uncertainties": ["The selected evidence item is not an image and was not visually analyzed."],
            "detail_used": None,
            "detail_escalation_reason": None,
        }, {}

    cached = db.scalar(select(EvidenceAiObservation).where(EvidenceAiObservation.evidence_id == evidence.id))
    if cached and cached.source_file_sha256 == file_obj.sha256:
        return dict(cached.content), {"cached": True, "calls": 0}

    storage = ObjectStorage(settings)
    image_bytes = storage.get_bytes(file_obj.storage_key)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    system = (
        "Analyze this site-walk photograph independently. You have no written process context. "
        "Describe only what the pixels visibly support. Keep operational interpretations cautious and separate from visible facts. "
        "Do not infer identity, company policy, process frequency, performance, financial impact, root cause, hidden system behavior, or workflow state that is not visible. "
        "If fine labels, screens, small objects, or dense spatial detail could materially change the operational observation, request high detail; otherwise do not. "
        "Return only JSON with keys visible_observations, operational_interpretations, uncertainties, detail_escalation_required, detail_escalation_reason. "
        "The first three values must be arrays of short strings. detail_escalation_required must be a boolean."
    )

    def analyze(detail: str) -> tuple[dict[str, Any], dict[str, Any]]:
        user_content = [
            {
                "type": "input_text",
                "text": (
                    f"Evidence reference: evidence:{evidence.id}. "
                    "Analyze the photograph itself. Do not use or infer any written discovery context."
                ),
            },
            {
                "type": "input_image",
                "image_url": f"data:{file_obj.mime_type};base64,{encoded}",
                "detail": detail,
            },
        ]
        return _call_json(
            settings,
            system=system,
            user_content=user_content,
            reasoning_effort="low",
            verbosity="low",
            max_output_tokens=1400,
        )

    usage_items: list[dict[str, Any]] = []
    content, usage = analyze("low")
    if usage:
        usage_items.append(usage)
    detail_used = "low"
    escalation_reason = str(content.get("detail_escalation_reason") or "").strip() or None
    if bool(content.get("detail_escalation_required")):
        content, high_usage = analyze("high")
        if high_usage:
            usage_items.append(high_usage)
        detail_used = "high"
        escalation_reason = escalation_reason or str(content.get("detail_escalation_reason") or "").strip() or None

    normalized = {
        "visible_observations": [str(item) for item in content.get("visible_observations") or []],
        "operational_interpretations": [str(item) for item in content.get("operational_interpretations") or []],
        "uncertainties": [str(item) for item in content.get("uncertainties") or []],
        "detail_used": detail_used,
        "detail_escalation_reason": escalation_reason,
    }
    if cached:
        cached.model = settings.openai_model
        cached.source_file_sha256 = file_obj.sha256
        cached.content = normalized
        cached.section_id = evidence.section_id
        cached.report_id = evidence.report_id
    else:
        db.add(
            EvidenceAiObservation(
                evidence_id=evidence.id,
                report_id=evidence.report_id,
                section_id=evidence.section_id,
                model=settings.openai_model,
                source_file_sha256=file_obj.sha256,
                content=normalized,
            )
        )
    db.flush()
    return normalized, _merge_usage(usage_items)


def _allowed_source_refs(snapshot: dict[str, Any]) -> set[str]:
    return {str(item.get("ref")) for item in snapshot.get("sources") or [] if item.get("ref")}


def _normalize_source_refs(value: Any, allowed: set[str]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for raw in value or []:
        if isinstance(raw, str):
            ref = raw
            label = raw
        elif isinstance(raw, dict):
            ref = str(raw.get("ref") or raw.get("source_ref") or "")
            label = str(raw.get("label") or raw.get("reason") or ref)
        else:
            continue
        if ref in allowed and not any(item["ref"] == ref for item in refs):
            refs.append({"ref": ref, "label": label})
    return refs


def _verify_observation_text(
    settings: Settings,
    snapshot: dict[str, Any],
    photo_observations: list[dict[str, Any]],
    enhanced_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "Verify factual support for the proposed current-operations narrative using only the supplied source packet. "
        "Mark a claim unsupported when it adds a customer fact, process step, frequency, cause, performance claim, numeric value, or certainty absent from the packet. "
        "Grammar, neutral transitions, and cautious wording are allowed. Return only JSON with verification_status and unsupported_claims. "
        "verification_status is PASSED only when every factual claim is supported; otherwise BLOCKED. unsupported_claims is an array of objects with text and reason."
    )
    payload = {
        "sources": snapshot.get("sources") or [],
        "photo_observations": photo_observations,
        "proposed_text": enhanced_text,
    }
    result, usage = _call_json(
        settings,
        system=system,
        user_content=json.dumps(payload, ensure_ascii=False),
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=1400,
    )
    unsupported = result.get("unsupported_claims") or []
    status = str(result.get("verification_status") or ("BLOCKED" if unsupported else "PASSED")).upper()
    if status not in {"PASSED", "BLOCKED"}:
        status = "BLOCKED" if unsupported else "PASSED"
    return {"verification_status": status, "unsupported_claims": unsupported}, usage


def generate_observation_draft(
    settings: Settings,
    snapshot: dict[str, Any],
    instructions: str | None,
    prior_suggestion: AiSuggestion | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate the user-visible text draft in one lean text-only model call."""
    prior_text = ""
    if prior_suggestion:
        prior_text = str(
            (prior_suggestion.content or {}).get("enhanced_text")
            or (prior_suggestion.content or {}).get("suggested_text")
            or ""
        ).strip()
    source_material = [
        item for item in snapshot.get("sources") or []
        if item.get("type") != "PHOTO"
    ]
    system = (
        "Rewrite the supplied CURRENT-operations discovery notes into concise professional customer-facing wording. "
        "Use only supplied facts. Preserve uncertainty. Do not add recommendations, benefits, root causes, frequencies, performance claims, or numbers that are not explicitly supplied. "
        "Do not analyze photographs. Return only JSON with enhanced_text, change_summary, gaps, source_refs, claims. "
        "Keep enhanced_text focused and normally no longer than the source material."
    )
    request_payload = {
        "section": snapshot.get("section"),
        "source_material": source_material,
        "user_refinement_instruction": instructions or None,
        "prior_enhanced_text": prior_text or None,
    }
    generated, usage = _call_json(
        settings,
        system=system,
        user_content=json.dumps(request_payload, ensure_ascii=False),
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=1800,
    )
    enhanced_text = str(generated.get("enhanced_text") or generated.get("suggested_text") or "").strip()
    if not enhanced_text:
        raise ValueError("AI did not return enhanced observation text.")
    allowed = {str(item.get("ref")) for item in source_material if item.get("ref")}
    source_refs = _normalize_source_refs(generated.get("source_refs"), allowed)
    if not source_refs:
        source_refs = [
            {"ref": str(item["ref"]), "label": str(item.get("label") or item["ref"])}
            for item in source_material
            if item.get("ref")
        ]
    content = {
        "original_text": str(snapshot.get("section", {}).get("original_narrative") or ""),
        "source_snapshot": {**snapshot, "selected_evidence_ids": []},
        "enhanced_text": enhanced_text,
        "suggested_text": enhanced_text,
        "change_summary": generated.get("change_summary") or [],
        "gaps": generated.get("gaps") or [],
        "claims": generated.get("claims") or [],
        "source_refs": source_refs,
        "photo_observations": [],
        "verification_status": "VERIFYING",
        "unsupported_claims": [],
        "accept_allowed": False,
        "refinement_instruction": instructions,
        "parent_suggestion_id": prior_suggestion.id if prior_suggestion else None,
        "source_section_version": snapshot.get("section", {}).get("version"),
        "workflow_stage": "DRAFT_READY",
    }
    return content, usage


def finalize_observation_draft(
    settings: Settings,
    snapshot: dict[str, Any],
    draft_content: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify the already-visible text draft and make at most one repair pass."""
    usage_items: list[dict[str, Any]] = []
    enhanced_text = str(draft_content.get("enhanced_text") or "").strip()
    verification, verify_usage = _verify_observation_text(settings, snapshot, [], enhanced_text)
    usage_items.append(verify_usage)

    if verification["verification_status"] == "BLOCKED" and verification["unsupported_claims"]:
        repair_system = (
            "Remove or cautiously rephrase every unsupported claim identified by the verifier. "
            "Use only supplied written sources and add no new facts. Return only JSON with enhanced_text."
        )
        repair_payload = {
            "sources": [item for item in snapshot.get("sources") or [] if item.get("type") != "PHOTO"],
            "proposed_text": enhanced_text,
            "unsupported_claims": verification["unsupported_claims"],
        }
        repaired, repair_usage = _call_json(
            settings,
            system=repair_system,
            user_content=json.dumps(repair_payload, ensure_ascii=False),
            reasoning_effort="low",
            verbosity="low",
            max_output_tokens=1600,
        )
        usage_items.append(repair_usage)
        repaired_text = str(repaired.get("enhanced_text") or "").strip()
        if repaired_text:
            enhanced_text = repaired_text
            verification, verify_usage_2 = _verify_observation_text(settings, snapshot, [], enhanced_text)
            usage_items.append(verify_usage_2)

    content = dict(draft_content)
    content.update({
        "enhanced_text": enhanced_text,
        "suggested_text": enhanced_text,
        "verification_status": verification["verification_status"],
        "unsupported_claims": verification["unsupported_claims"],
        "accept_allowed": verification["verification_status"] == "PASSED",
        "workflow_stage": "COMPLETED",
    })
    return content, _merge_usage(usage_items)


def run_observation_enhancement(
    db: Session,
    settings: Settings,
    snapshot: dict[str, Any],
    instructions: str | None,
    prior_suggestion: AiSuggestion | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Synchronous compatibility wrapper used by tests and non-worker callers."""
    draft, draft_usage = generate_observation_draft(settings, snapshot, instructions, prior_suggestion)
    final, verify_usage = finalize_observation_draft(settings, snapshot, draft)
    return final, _merge_usage([draft_usage, verify_usage])


def build_photo_context_snapshot(
    db: Session,
    report: Report,
    section: ReportSection,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Combine stored independent photo observations with written discovery context."""
    written = build_observation_snapshot(db, report, section, [])
    selected_ids = list(dict.fromkeys(evidence_ids or []))
    stmt = (
        select(EvidenceAiObservation, EvidenceItem)
        .join(EvidenceItem, EvidenceAiObservation.evidence_id == EvidenceItem.id)
        .where(
            EvidenceAiObservation.report_id == report.id,
            EvidenceItem.report_id == report.id,
            EvidenceItem.section_id == section.id,
            EvidenceItem.evidence_type == "PHOTO",
        )
        .order_by(EvidenceItem.created_at)
    )
    if selected_ids:
        stmt = stmt.where(EvidenceItem.id.in_(selected_ids))
    rows = list(db.execute(stmt).all())
    if selected_ids:
        found = {evidence.id for _, evidence in rows}
        missing = [item_id for item_id in selected_ids if item_id not in found]
        if missing:
            raise ValueError("One or more selected photographs have not completed independent AI analysis.")
    if not rows:
        raise ValueError("Analyze at least one photograph before comparing photographs to Current Operations.")
    photos = [
        {
            "ref": f"evidence:{evidence.id}",
            "evidence_id": evidence.id,
            "caption": evidence.caption,
            "analysis": dict(analysis.content or {}),
            "model": analysis.model,
            "source_file_sha256": analysis.source_file_sha256,
        }
        for analysis, evidence in rows
    ]
    return {
        "purpose": "PHOTO_CONTEXT_REVISION",
        "report": written["report"],
        "section": written["section"],
        "sources": [item for item in written.get("sources") or [] if item.get("type") != "PHOTO"],
        "photo_observations": photos,
        "selected_evidence_ids": [item["evidence_id"] for item in photos],
    }


def run_photo_context_revision(
    settings: Settings,
    snapshot: dict[str, Any],
    instructions: str | None,
    prior_suggestion: AiSuggestion | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    usage_items: list[dict[str, Any]] = []
    prior_text = ""
    if prior_suggestion:
        prior_text = str((prior_suggestion.content or {}).get("suggested_text") or "").strip()
    system = (
        "Compare independent site-photo observations with the written CURRENT-operations discovery. "
        "The photo observations were created without written context. Use the written material only now to interpret relevance. "
        "Classify what the photos support, what useful context they add, any potential conflict, and any open question. "
        "Then suggest a revised current-operations narrative using only facts supported by the written sources or independent photo observations. "
        "Do not add solution language, benefits, hidden process state, root cause, frequency, performance, or financial claims. "
        "Return only JSON with supports, adds_context, potential_conflicts, open_questions, suggested_text, source_refs, claims."
    )
    request_payload = {
        "section": snapshot.get("section"),
        "written_sources": snapshot.get("sources") or [],
        "independent_photo_observations": snapshot.get("photo_observations") or [],
        "user_refinement_instruction": instructions or None,
        "prior_suggested_text": prior_text or None,
    }
    generated, usage = _call_json(
        settings,
        system=system,
        user_content=json.dumps(request_payload, ensure_ascii=False),
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=2200,
    )
    usage_items.append(usage)
    suggested_text = str(generated.get("suggested_text") or generated.get("enhanced_text") or "").strip()
    if not suggested_text:
        raise ValueError("AI did not return a photo-context revision.")
    verification_photo_payload = [
        {
            "ref": photo.get("ref"),
            **dict(photo.get("analysis") or {}),
        }
        for photo in snapshot.get("photo_observations") or []
    ]
    verification, verify_usage = _verify_observation_text(settings, snapshot, verification_photo_payload, suggested_text)
    usage_items.append(verify_usage)
    if verification["verification_status"] == "BLOCKED" and verification["unsupported_claims"]:
        repair_system = (
            "Rewrite the proposed narrative to remove every unsupported claim. Use only supplied written sources and independent photo observations. "
            "Do not add new facts. Return only JSON with suggested_text."
        )
        repaired, repair_usage = _call_json(
            settings,
            system=repair_system,
            user_content=json.dumps({
                "written_sources": snapshot.get("sources") or [],
                "photo_observations": snapshot.get("photo_observations") or [],
                "proposed_text": suggested_text,
                "unsupported_claims": verification["unsupported_claims"],
            }, ensure_ascii=False),
            reasoning_effort="low",
            verbosity="low",
            max_output_tokens=1800,
        )
        usage_items.append(repair_usage)
        repaired_text = str(repaired.get("suggested_text") or repaired.get("enhanced_text") or "").strip()
        if repaired_text:
            suggested_text = repaired_text
            verification, verify_usage_2 = _verify_observation_text(settings, snapshot, verification_photo_payload, suggested_text)
            usage_items.append(verify_usage_2)

    allowed = {str(item.get("ref")) for item in snapshot.get("sources") or [] if item.get("ref")}
    allowed.update(str(item.get("ref")) for item in snapshot.get("photo_observations") or [] if item.get("ref"))
    source_refs = _normalize_source_refs(generated.get("source_refs"), allowed)
    if not source_refs:
        source_refs = [
            {"ref": str(item.get("ref")), "label": str(item.get("label") or item.get("caption") or item.get("ref"))}
            for item in [*(snapshot.get("sources") or []), *(snapshot.get("photo_observations") or [])]
            if item.get("ref")
        ]
    content = {
        "original_text": str(snapshot.get("section", {}).get("original_narrative") or ""),
        "source_snapshot": snapshot,
        "supports": generated.get("supports") or [],
        "adds_context": generated.get("adds_context") or [],
        "potential_conflicts": generated.get("potential_conflicts") or [],
        "open_questions": generated.get("open_questions") or [],
        "suggested_text": suggested_text,
        "enhanced_text": suggested_text,
        "claims": generated.get("claims") or [],
        "source_refs": source_refs,
        "verification_status": verification["verification_status"],
        "unsupported_claims": verification["unsupported_claims"],
        "accept_allowed": verification["verification_status"] == "PASSED",
        "refinement_instruction": instructions,
        "parent_suggestion_id": prior_suggestion.id if prior_suggestion else None,
        "source_section_version": snapshot.get("section", {}).get("version"),
    }
    return content, _merge_usage(usage_items)

def _terms(value: str) -> set[str]:
    stop = {
        "and", "the", "for", "with", "that", "this", "from", "into", "are", "was", "were", "have", "has", "had",
        "their", "they", "them", "using", "used", "use", "through", "then", "than", "where", "when", "while", "will",
        "would", "could", "should", "can", "not", "but", "also", "each", "other", "more", "most", "some", "any", "all",
        "current", "process", "operation", "operations", "inventory", "cloud",
    }
    return {token for token in re.findall(r"[a-z0-9]{3,}", (value or "").lower()) if token not in stop}


def _module_text(value: str | None) -> str:
    return (value or "").replace("_", " ").strip().lower()


def _capability_relevant_to_module(capability: Capability, module: str | None) -> bool:
    if not module:
        return True
    target = _module_text(module)
    domain = _module_text(capability.domain)
    if target in domain or domain in target:
        return True
    # These domains routinely support multiple operational areas and are useful
    # as supporting capabilities without broadening retrieval to the full catalog.
    return any(token in domain for token in ("cross-process", "integration", "reporting"))


def _knowledge_relevance_score(entry: KnowledgeEntry, module: str | None, query_terms: set[str]) -> int:
    score = 0
    entry_module = _module_text(entry.process_module)
    target = _module_text(module)
    if target and entry_module:
        if target == entry_module:
            score += 30
        elif target in entry_module or entry_module in target:
            score += 20
    elif not entry_module:
        score += 3
    overlap = len(query_terms & _terms(f"{entry.title} {entry.content}"))
    score += min(overlap, 20) * 2
    if entry.capability_id:
        score += 5
    return score


def build_solution_snapshot(db: Session, report: Report, section: ReportSection) -> dict[str, Any]:
    """Build the controlled context for a Cloud Inventory solution narrative.

    General narrative and guided-response notes are deliberately exposed as
    OBSERVATION sources even when a contributor did not create a formal Finding.
    This makes them first-class mapping evidence without manufacturing database
    findings or changing the contributor's original classification.
    """
    response_rows = db.execute(
        select(Response, PromptDefinition)
        .join(PromptDefinition, Response.prompt_id == PromptDefinition.id)
        .where(Response.section_id == section.id, PromptDefinition.active.is_(True))
        .order_by(PromptDefinition.display_order)
    ).all()
    findings = list(
        db.scalars(
            select(Finding)
            .where(Finding.report_id == report.id, Finding.section_id == section.id, Finding.status != "REJECTED")
            .order_by(Finding.created_at)
        ).all()
    )
    metrics = list(
        db.scalars(
            select(Metric)
            .where(Metric.report_id == report.id, Metric.section_id == section.id)
            .order_by(Metric.created_at)
        ).all()
    )

    operational_sources: list[dict[str, Any]] = []
    if section.narrative.strip():
        operational_sources.append({
            "ref": "section:narrative",
            "source_type": "GENERAL_OBSERVATION",
            "finding_type": "OBSERVATION",
            "label": "Observation — Current operations narrative",
            "text": section.narrative.strip(),
        })
    for response, prompt in response_rows:
        text = response.narrative.strip() or (json.dumps(response.payload, ensure_ascii=False) if response.payload else "")
        if not text:
            continue
        operational_sources.append({
            "ref": f"response:{response.id}",
            "source_type": "GENERAL_OBSERVATION",
            "finding_type": "OBSERVATION",
            "label": f"Observation — {prompt.question}",
            "text": text,
        })
    for finding in findings:
        text = finding.statement.strip()
        if finding.impact:
            text += f"\nImpact noted by contributor: {finding.impact.strip()}"
        operational_sources.append({
            "ref": f"finding:{finding.id}",
            "source_type": "FINDING",
            "finding_type": finding.finding_type,
            "finding_id": finding.id,
            "label": f"{finding.finding_type.replace('_', ' ').title()} — {finding.statement[:120]}",
            "text": text,
        })

    metric_sources: list[dict[str, Any]] = []
    for metric in metrics:
        value = metric.value_text if metric.value_text is not None else metric.value_numeric
        if value is None:
            continue
        metric_sources.append({
            "ref": f"metric:{metric.id}",
            "label": metric.name,
            "text": f"{metric.name}: {value}{' ' + metric.unit if metric.unit else ''}{' (' + metric.period + ')' if metric.period else ''}",
        })

    approved_capabilities = [
        item for item in db.scalars(
            select(Capability).where(Capability.status == "APPROVED").order_by(Capability.domain, Capability.name)
        ).all()
        if _capability_relevant_to_module(item, section.process_module)
    ]

    query_terms = _terms(" ".join(item["text"] for item in operational_sources) + " " + " ".join(item["text"] for item in metric_sources))
    accessible_knowledge = list(
        db.scalars(
            select(KnowledgeEntry)
            .where(
                KnowledgeEntry.approval_state == "APPROVED",
                or_(KnowledgeEntry.expires_at.is_(None), KnowledgeEntry.expires_at > utcnow()),
                or_(KnowledgeEntry.prospect_id == report.prospect_id, KnowledgeEntry.reusable_across_prospects.is_(True)),
            )
            .order_by(KnowledgeEntry.updated_at.desc())
            .limit(500)
        ).all()
    )
    approved_capability_ids = {item.id for item in approved_capabilities}
    ranked_knowledge: list[tuple[int, KnowledgeEntry]] = []
    for entry in accessible_knowledge:
        if entry.capability_id and entry.capability_id not in approved_capability_ids:
            # Knowledge tied to a non-approved capability may not be used to make
            # product claims in the solution narrative.
            continue
        score = _knowledge_relevance_score(entry, section.process_module, query_terms)
        if score > 0:
            ranked_knowledge.append((score, entry))
    ranked_knowledge.sort(key=lambda pair: (-pair[0], pair[1].title.lower()))
    selected_knowledge = [entry for _, entry in ranked_knowledge[:20]]

    current_solution = db.scalar(
        select(SectionContentVersion)
        .where(
            SectionContentVersion.report_id == report.id,
            SectionContentVersion.section_id == section.id,
            SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH",
            SectionContentVersion.is_current.is_(True),
        )
        .order_by(SectionContentVersion.version.desc())
    )

    return {
        "purpose": "SOLUTION_APPROACH",
        "report": {"id": report.id, "title": report.title, "revision": report.revision},
        "section": {
            "id": section.id,
            "title": section.title,
            "process_module": section.process_module,
            "version": section.version,
        },
        "operational_sources": operational_sources,
        "metrics": metric_sources,
        "approved_capabilities": [
            {
                "ref": f"capability:{capability.id}",
                "id": capability.id,
                "code": capability.capability_code,
                "name": capability.name,
                "domain": capability.domain,
                "description": capability.controlled_description,
                "prerequisites": capability.typical_prerequisites,
                "limitations": capability.limitations,
                "source": capability.source,
                "version": capability.version,
            }
            for capability in approved_capabilities
        ],
        "approved_knowledge": [
            {
                "ref": f"knowledge:{entry.id}",
                "id": entry.id,
                "title": entry.title,
                "process_module": entry.process_module,
                "content": entry.content[:5000],
                "source_type": entry.source_type,
                "source_ref": entry.source_ref,
                "capability_id": entry.capability_id,
                "prospect_specific": entry.prospect_id is not None,
                "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
            }
            for entry in selected_knowledge
        ],
        "current_solution": None if not current_solution else {
            "version": current_solution.version,
            "text": current_solution.text,
            "source_type": current_solution.source_type,
        },
    }


def _solution_allowed_refs(snapshot: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    operational = {str(item["ref"]) for item in snapshot.get("operational_sources") or [] if item.get("ref")}
    capabilities = {str(item["id"]) for item in snapshot.get("approved_capabilities") or [] if item.get("id")}
    knowledge = {str(item["ref"]) for item in snapshot.get("approved_knowledge") or [] if item.get("ref")}
    return operational, capabilities, knowledge


def _normalize_solution_mappings(value: Any, snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    operational_refs, capability_ids, knowledge_refs = _solution_allowed_refs(snapshot)
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for raw in value or []:
        if not isinstance(raw, dict):
            errors.append("A capability mapping was not an object.")
            continue
        capability_id = str(raw.get("capability_id") or raw.get("id") or "")
        source_ref = str(raw.get("source_ref") or "")
        if capability_id not in capability_ids:
            errors.append(f"Capability reference {capability_id or '(missing)'} is not approved for this solution context.")
            continue
        if source_ref not in operational_refs:
            errors.append(f"Operational source {source_ref or '(missing)'} is not available in this section.")
            continue
        pair = (source_ref, capability_id)
        if pair in seen:
            continue
        seen.add(pair)
        refs = [str(item) for item in raw.get("knowledge_refs") or [] if str(item) in knowledge_refs]
        normalized.append({
            "capability_id": capability_id,
            "source_ref": source_ref,
            "rationale": str(raw.get("rationale") or raw.get("reason") or "").strip(),
            "prerequisites": str(raw.get("prerequisites") or "").strip() or None,
            "limitations": str(raw.get("limitations") or "").strip() or None,
            "knowledge_refs": refs,
        })
    return normalized, errors


def _verify_solution_text(settings: Settings, snapshot: dict[str, Any], solution_text: str, mappings: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "You are a product-claim verifier for a Cloud Inventory customer-facing discovery report. "
        "Evaluate the proposed solution narrative only against the supplied APPROVED capability definitions, APPROVED knowledge, operational observations, and mappings. "
        "Do not use external knowledge. Block claims that invent functionality, configuration behavior, integration behavior, performance improvement, implementation commitment, guarantee, or customer fact. "
        "A capability may be described only within its controlled description, prerequisites, and limitations. Historical knowledge may clarify wording but may not override a capability limitation. "
        "Return only JSON with keys verification_status and unsupported_claims. verification_status must be PASSED or BLOCKED."
    )
    payload = {
        "operational_sources": snapshot.get("operational_sources") or [],
        "approved_capabilities": snapshot.get("approved_capabilities") or [],
        "approved_knowledge": snapshot.get("approved_knowledge") or [],
        "capability_mappings": mappings,
        "proposed_solution_text": solution_text,
    }
    result, usage = _call_json(settings, system=system, user_content=json.dumps(payload, ensure_ascii=False))
    unsupported = result.get("unsupported_claims") or []
    status = str(result.get("verification_status") or ("BLOCKED" if unsupported else "PASSED")).upper()
    if status not in {"PASSED", "BLOCKED"}:
        status = "BLOCKED" if unsupported else "PASSED"
    return {"verification_status": status, "unsupported_claims": unsupported}, usage


def run_solution_approach(
    settings: Settings,
    snapshot: dict[str, Any],
    instructions: str | None,
    prior_suggestion: AiSuggestion | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not snapshot.get("operational_sources"):
        raise ValueError("Enter current operations notes or findings before generating a Cloud Inventory approach.")
    if not snapshot.get("approved_capabilities"):
        raise ValueError("No approved Cloud Inventory capabilities are available for this operational area.")

    usage_items: list[dict[str, Any]] = []
    prior_text = ""
    if prior_suggestion:
        prior_text = str((prior_suggestion.content or {}).get("solution_text") or (prior_suggestion.content or {}).get("suggested_text") or "").strip()

    system = (
        "You are a senior Cloud Inventory solution consultant drafting the 'Cloud Inventory Approach' section of a professional customer discovery report. "
        "Use only the supplied operational observations/findings, approved capability catalog, approved knowledge, and metrics. "
        "General notes and guided responses marked GENERAL_OBSERVATION must be treated as observations when determining relevant functionality. "
        "Do not manufacture pain points from neutral observations. Do not invent product functionality, integrations, configuration, guarantees, performance improvements, or implementation commitments. "
        "State prerequisites or limitations when material. Write in clear customer-facing prose explaining how relevant approved Cloud Inventory functionality can support the observed operation. "
        "Return only JSON with keys solution_text, capability_mappings, gaps, source_refs. "
        "capability_mappings must be an array of objects with capability_id, source_ref, rationale, prerequisites, limitations, knowledge_refs. "
        "Every capability_id must come from approved_capabilities. Every source_ref must come from operational_sources. Every knowledge_refs value must come from approved_knowledge."
    )
    payload = {
        "section": snapshot.get("section"),
        "operational_sources": snapshot.get("operational_sources") or [],
        "metrics": snapshot.get("metrics") or [],
        "approved_capabilities": snapshot.get("approved_capabilities") or [],
        "approved_knowledge": snapshot.get("approved_knowledge") or [],
        "current_accepted_solution": snapshot.get("current_solution"),
        "prior_ai_solution": prior_text or None,
        "user_refinement_instruction": instructions or None,
    }
    generated, usage = _call_json(settings, system=system, user_content=json.dumps(payload, ensure_ascii=False))
    usage_items.append(usage)
    solution_text = str(generated.get("solution_text") or generated.get("suggested_text") or "").strip()
    if not solution_text:
        raise ValueError("AI did not return a Cloud Inventory approach narrative.")
    mappings, mapping_errors = _normalize_solution_mappings(generated.get("capability_mappings"), snapshot)
    if not mappings:
        mapping_errors.append("The solution narrative did not include any valid capability-to-observation mapping.")

    verification, verify_usage = _verify_solution_text(settings, snapshot, solution_text, mappings)
    usage_items.append(verify_usage)
    if mapping_errors:
        verification["verification_status"] = "BLOCKED"
        verification["unsupported_claims"] = list(verification.get("unsupported_claims") or []) + [
            {"text": "Capability mapping validation", "reason": error} for error in mapping_errors
        ]

    # One repair attempt is permitted. It may remove unsupported product claims
    # or invalid mappings but may not broaden the approved source packet.
    if verification["verification_status"] == "BLOCKED":
        repair_system = (
            "Repair the proposed Cloud Inventory approach using only the supplied approved source packet. Remove unsupported claims and invalid mappings. "
            "Do not add new capabilities or operational facts. Return only JSON with keys solution_text and capability_mappings using the same mapping schema."
        )
        repair_payload = {
            "operational_sources": snapshot.get("operational_sources") or [],
            "approved_capabilities": snapshot.get("approved_capabilities") or [],
            "approved_knowledge": snapshot.get("approved_knowledge") or [],
            "proposed_solution_text": solution_text,
            "proposed_mappings": mappings,
            "issues": verification.get("unsupported_claims") or [],
        }
        repaired, repair_usage = _call_json(settings, system=repair_system, user_content=json.dumps(repair_payload, ensure_ascii=False))
        usage_items.append(repair_usage)
        repaired_text = str(repaired.get("solution_text") or "").strip()
        repaired_mappings, repair_errors = _normalize_solution_mappings(repaired.get("capability_mappings"), snapshot)
        if repaired_text and repaired_mappings:
            solution_text = repaired_text
            mappings = repaired_mappings
            verification, verify_usage_2 = _verify_solution_text(settings, snapshot, solution_text, mappings)
            usage_items.append(verify_usage_2)
            if repair_errors:
                verification["verification_status"] = "BLOCKED"
                verification["unsupported_claims"] = list(verification.get("unsupported_claims") or []) + [
                    {"text": "Capability mapping validation", "reason": error} for error in repair_errors
                ]

    operational_lookup = {item["ref"]: item for item in snapshot.get("operational_sources") or []}
    capability_lookup = {item["id"]: item for item in snapshot.get("approved_capabilities") or []}
    source_refs: list[dict[str, Any]] = []
    for mapping in mappings:
        operational = operational_lookup.get(mapping["source_ref"])
        capability = capability_lookup.get(mapping["capability_id"])
        if operational:
            source_refs.append({"ref": mapping["source_ref"], "label": operational.get("label") or mapping["source_ref"]})
        if capability:
            ref = f"capability:{capability['id']}"
            source_refs.append({"ref": ref, "label": f"{capability['code']} — {capability['name']}"})
        for knowledge_ref in mapping.get("knowledge_refs") or []:
            knowledge = next((item for item in snapshot.get("approved_knowledge") or [] if item.get("ref") == knowledge_ref), None)
            if knowledge:
                source_refs.append({"ref": knowledge_ref, "label": knowledge.get("title") or knowledge_ref})
    deduped_refs: list[dict[str, Any]] = []
    for ref in source_refs:
        if not any(item["ref"] == ref["ref"] for item in deduped_refs):
            deduped_refs.append(ref)

    content = {
        "current_solution_text": str((snapshot.get("current_solution") or {}).get("text") or ""),
        "solution_text": solution_text,
        "suggested_text": solution_text,
        "capability_mappings": mappings,
        "gaps": generated.get("gaps") or [],
        "source_refs": deduped_refs,
        "source_snapshot": snapshot,
        "verification_status": verification["verification_status"],
        "unsupported_claims": verification.get("unsupported_claims") or [],
        "accept_allowed": verification["verification_status"] == "PASSED" and bool(mappings),
        "refinement_instruction": instructions,
        "parent_suggestion_id": prior_suggestion.id if prior_suggestion else None,
        "source_section_version": snapshot.get("section", {}).get("version"),
    }
    return content, _merge_usage(usage_items)



BENEFIT_CATEGORIES = {
    "OPERATIONAL_EFFICIENCY",
    "INVENTORY_VISIBILITY",
    "ACCURACY_CONTROL",
    "CUSTOMER_SERVICE",
    "WORKFORCE_PRODUCTIVITY",
    "COMPLIANCE_TRACEABILITY",
    "MANAGEMENT_VISIBILITY",
    "SCALABILITY",
}


def build_targeted_benefits_snapshot(db: Session, report: Report, section: ReportSection) -> dict[str, Any]:
    """Build a source packet for benefits tied to one operational section."""
    solution_snapshot = build_solution_snapshot(db, report, section)
    solution = db.scalar(
        select(SectionContentVersion)
        .where(
            SectionContentVersion.report_id == report.id,
            SectionContentVersion.section_id == section.id,
            SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH",
            SectionContentVersion.is_current.is_(True),
        )
        .order_by(SectionContentVersion.version.desc())
    )
    mappings = db.execute(
        select(CapabilityMapping, Capability)
        .join(Capability, CapabilityMapping.capability_id == Capability.id)
        .where(
            CapabilityMapping.report_id == report.id,
            CapabilityMapping.section_id == section.id,
            CapabilityMapping.approval_state == "APPROVED",
            Capability.status == "APPROVED",
        )
        .order_by(Capability.name)
    ).all()
    metrics = list(
        db.scalars(
            select(Metric)
            .where(Metric.report_id == report.id, Metric.section_id == section.id)
            .order_by(Metric.created_at)
        ).all()
    )
    existing = list(
        db.scalars(
            select(Benefit)
            .where(Benefit.report_id == report.id, Benefit.section_id == section.id, Benefit.approval_state != "REJECTED")
            .order_by(Benefit.created_at)
        ).all()
    )
    return {
        "purpose": "TARGETED_BENEFITS",
        "report": {"id": report.id, "title": report.title, "revision": report.revision},
        "section": {
            "id": section.id,
            "title": section.title,
            "process_module": section.process_module,
            "version": section.version,
        },
        "operational_sources": solution_snapshot.get("operational_sources") or [],
        "solution": None if not solution else {
            "ref": f"solution:{solution.id}",
            "id": solution.id,
            "version": solution.version,
            "text": solution.text,
            "source_type": solution.source_type,
        },
        "approved_mappings": [
            {
                "ref": f"mapping:{mapping.id}",
                "id": mapping.id,
                "source_ref": mapping.source_ref,
                "source_label": mapping.source_label,
                "source_statement": mapping.source_statement,
                "rationale": mapping.rationale,
                "prerequisites": mapping.prerequisites or capability.typical_prerequisites,
                "capability": {
                    "id": capability.id,
                    "code": capability.capability_code,
                    "name": capability.name,
                    "description": capability.controlled_description,
                    "limitations": capability.limitations,
                    "version": capability.version,
                },
            }
            for mapping, capability in mappings
        ],
        "metrics": [
            {
                "ref": f"metric:{metric.id}",
                "id": metric.id,
                "name": metric.name,
                "value_numeric": metric.value_numeric,
                "value_text": metric.value_text,
                "unit": metric.unit,
                "period": metric.period,
                "source": metric.source,
                "confidence": metric.confidence,
            }
            for metric in metrics
        ],
        "existing_benefits": [
            {
                "id": item.id,
                "statement": item.statement,
                "category": item.category,
                "measure_type": item.measure_type,
                "approval_state": item.approval_state,
            }
            for item in existing
        ],
    }


def _benefit_allowed_refs(snapshot: dict[str, Any]) -> set[str]:
    refs = {str(item.get("ref")) for item in snapshot.get("operational_sources") or [] if item.get("ref")}
    refs.update(str(item.get("ref")) for item in snapshot.get("approved_mappings") or [] if item.get("ref"))
    refs.update(str(item.get("ref")) for item in snapshot.get("metrics") or [] if item.get("ref"))
    solution = snapshot.get("solution") or {}
    if solution.get("ref"):
        refs.add(str(solution["ref"]))
    return refs


def _normalize_targeted_benefits(value: Any, snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    allowed_refs = _benefit_allowed_refs(snapshot)
    metric_refs = {str(item.get("ref")) for item in snapshot.get("metrics") or [] if item.get("ref")}
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(value or []):
        if not isinstance(raw, dict):
            errors.append(f"Benefit {index + 1} was not an object.")
            continue
        statement = str(raw.get("statement") or raw.get("text") or "").strip()
        if not statement:
            errors.append(f"Benefit {index + 1} did not contain a statement.")
            continue
        key = statement.casefold()
        if key in seen:
            continue
        seen.add(key)
        category = str(raw.get("category") or "OPERATIONAL_EFFICIENCY").upper()
        if category not in BENEFIT_CATEGORIES:
            category = "OPERATIONAL_EFFICIENCY"
        measure_type = str(raw.get("measure_type") or "QUALITATIVE").upper()
        if measure_type not in {"QUALITATIVE", "QUANTITATIVE"}:
            measure_type = "QUALITATIVE"
        source_refs = [str(ref) for ref in raw.get("source_refs") or [] if str(ref) in allowed_refs]
        if not source_refs:
            errors.append(f"Benefit {index + 1} was not linked to an operational, solution, mapping, or metric source.")
        formula = str(raw.get("formula") or "").strip() or None
        assumptions = str(raw.get("assumptions") or "").strip() or None
        if measure_type == "QUANTITATIVE":
            if not any(ref in metric_refs for ref in source_refs):
                errors.append(f"Quantitative benefit {index + 1} does not reference a recorded metric.")
            if not formula or not assumptions:
                errors.append(f"Quantitative benefit {index + 1} requires a formula and explicit assumptions.")
        elif re.search(r"(?<![A-Za-z])\d+(?:\.\d+)?\s*%", statement):
            errors.append(f"Qualitative benefit {index + 1} contains an unsupported percentage claim.")
        confidence = str(raw.get("confidence") or "MEDIUM").upper()
        if confidence not in {"LOW", "MEDIUM", "HIGH"}:
            confidence = "MEDIUM"
        normalized.append({
            "statement": statement,
            "category": category,
            "measure_type": measure_type,
            "formula": formula,
            "assumptions": assumptions,
            "confidence": confidence,
            "source_refs": source_refs,
        })
    return normalized, errors


def _verify_targeted_benefits(
    settings: Settings,
    snapshot: dict[str, Any],
    benefits: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "You verify targeted benefit statements for a customer discovery report. Use only the supplied current-operation sources, "
        "accepted Cloud Inventory approach, approved capability mappings, and recorded metrics. Do not use external knowledge. "
        "Block invented outcomes, guarantees, financial results, performance percentages, time savings, accuracy improvements, or numeric claims without an explicit metric, formula, and assumptions. "
        "Qualitative benefits may describe the direction of expected operational value but must not present an unvalidated result as achieved. "
        "Return only JSON with verification_status (PASSED or BLOCKED) and unsupported_claims."
    )
    payload = {
        "operational_sources": snapshot.get("operational_sources") or [],
        "solution": snapshot.get("solution"),
        "approved_mappings": snapshot.get("approved_mappings") or [],
        "metrics": snapshot.get("metrics") or [],
        "proposed_benefits": benefits,
    }
    result, usage = _call_json(settings, system=system, user_content=json.dumps(payload, ensure_ascii=False))
    unsupported = result.get("unsupported_claims") or []
    status = str(result.get("verification_status") or ("BLOCKED" if unsupported else "PASSED")).upper()
    if status not in {"PASSED", "BLOCKED"}:
        status = "BLOCKED" if unsupported else "PASSED"
    return {"verification_status": status, "unsupported_claims": unsupported}, usage


def run_targeted_benefits(
    settings: Settings,
    snapshot: dict[str, Any],
    instructions: str | None,
    prior_suggestion: AiSuggestion | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not snapshot.get("operational_sources"):
        raise ValueError("Enter current operations notes or findings before generating targeted benefits.")
    if not snapshot.get("solution") and not snapshot.get("approved_mappings"):
        raise ValueError("Enter or accept a Cloud Inventory approach, or approve a capability mapping, before generating targeted benefits.")
    prior = []
    if prior_suggestion:
        prior = list((prior_suggestion.content or {}).get("benefits") or [])
    usage_items: list[dict[str, Any]] = []
    system = (
        "You are a senior Cloud Inventory value consultant drafting concise targeted benefits for one operational area. "
        "Use only the supplied current-operation sources, accepted Cloud Inventory approach, approved capability mappings, and metrics. "
        "Do not invent problems from neutral observations. Do not create guarantees or unsupported numeric improvements. "
        "Use QUALITATIVE unless an explicit recorded metric supports a QUANTITATIVE statement with a formula and assumptions. "
        "Return only JSON with benefits and gaps. benefits must be an array of objects with statement, category, measure_type, formula, assumptions, confidence, and source_refs."
    )
    payload = {
        "section": snapshot.get("section"),
        "operational_sources": snapshot.get("operational_sources") or [],
        "accepted_solution": snapshot.get("solution"),
        "approved_mappings": snapshot.get("approved_mappings") or [],
        "metrics": snapshot.get("metrics") or [],
        "existing_benefits": snapshot.get("existing_benefits") or [],
        "prior_ai_benefits": prior,
        "user_refinement_instruction": instructions or None,
    }
    generated, usage = _call_json(settings, system=system, user_content=json.dumps(payload, ensure_ascii=False))
    usage_items.append(usage)
    benefits, validation_errors = _normalize_targeted_benefits(generated.get("benefits") or generated.get("benefit_statements"), snapshot)
    if not benefits:
        validation_errors.append("No valid targeted benefit statements were generated.")
    verification, verify_usage = _verify_targeted_benefits(settings, snapshot, benefits)
    usage_items.append(verify_usage)
    if validation_errors:
        verification["verification_status"] = "BLOCKED"
        verification["unsupported_claims"] = list(verification.get("unsupported_claims") or []) + [
            {"text": "Benefit validation", "reason": error} for error in validation_errors
        ]
    if verification["verification_status"] == "BLOCKED":
        repair_system = (
            "Repair the targeted benefits using only the supplied source packet. Remove unsupported numeric claims, guarantees, and ungrounded statements. "
            "Return only JSON with benefits using the same schema."
        )
        repaired, repair_usage = _call_json(
            settings,
            system=repair_system,
            user_content=json.dumps({
                "source_packet": snapshot,
                "proposed_benefits": benefits,
                "issues": verification.get("unsupported_claims") or [],
            }, ensure_ascii=False),
        )
        usage_items.append(repair_usage)
        repaired_benefits, repaired_errors = _normalize_targeted_benefits(repaired.get("benefits"), snapshot)
        if repaired_benefits:
            benefits = repaired_benefits
            verification, verify_usage_2 = _verify_targeted_benefits(settings, snapshot, benefits)
            usage_items.append(verify_usage_2)
            if repaired_errors:
                verification["verification_status"] = "BLOCKED"
                verification["unsupported_claims"] = list(verification.get("unsupported_claims") or []) + [
                    {"text": "Benefit validation", "reason": error} for error in repaired_errors
                ]
    label_lookup = {str(item.get("ref")): item.get("label") or item.get("name") or item.get("ref") for item in snapshot.get("operational_sources") or []}
    for item in snapshot.get("approved_mappings") or []:
        label_lookup[str(item.get("ref"))] = f"{item.get('capability', {}).get('code')} — {item.get('capability', {}).get('name')}"
    for item in snapshot.get("metrics") or []:
        label_lookup[str(item.get("ref"))] = item.get("name") or item.get("ref")
    if snapshot.get("solution"):
        label_lookup[str(snapshot["solution"].get("ref"))] = "Accepted Cloud Inventory approach"
    source_refs = []
    for benefit in benefits:
        for ref in benefit.get("source_refs") or []:
            if not any(item.get("ref") == ref for item in source_refs):
                source_refs.append({"ref": ref, "label": label_lookup.get(ref, ref)})
    content = {
        "benefits": benefits,
        "benefit_statements": benefits,
        "gaps": generated.get("gaps") or [],
        "source_refs": source_refs,
        "source_snapshot": snapshot,
        "verification_status": verification["verification_status"],
        "unsupported_claims": verification.get("unsupported_claims") or [],
        "accept_allowed": verification["verification_status"] == "PASSED" and bool(benefits),
        "refinement_instruction": instructions,
        "parent_suggestion_id": prior_suggestion.id if prior_suggestion else None,
        "source_section_version": snapshot.get("section", {}).get("version"),
        "source_report_revision": snapshot.get("report", {}).get("revision"),
    }
    return content, _merge_usage(usage_items)


def build_demo_plan_snapshot(db: Session, report: Report) -> dict[str, Any]:
    settings = db.get(DemoPlanSettings, report.id)
    priority_rows = list(
        db.scalars(select(DemoSectionPriority).where(DemoSectionPriority.report_id == report.id)).all()
    )
    priorities = {item.section_id: item for item in priority_rows}
    sections = list(
        db.scalars(
            select(ReportSection)
            .where(ReportSection.report_id == report.id, ReportSection.state != "REMOVED")
            .order_by(ReportSection.display_order)
        ).all()
    )
    section_packets: list[dict[str, Any]] = []
    all_refs: list[dict[str, Any]] = []
    for section in sections:
        priority = priorities.get(section.id)
        solution = db.scalar(
            select(SectionContentVersion)
            .where(
                SectionContentVersion.report_id == report.id,
                SectionContentVersion.section_id == section.id,
                SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH",
                SectionContentVersion.is_current.is_(True),
            )
            .order_by(SectionContentVersion.version.desc())
        )
        source_snapshot = build_solution_snapshot(db, report, section)
        mappings = db.execute(
            select(CapabilityMapping, Capability)
            .join(Capability, CapabilityMapping.capability_id == Capability.id)
            .where(
                CapabilityMapping.report_id == report.id,
                CapabilityMapping.section_id == section.id,
                CapabilityMapping.approval_state == "APPROVED",
                Capability.status == "APPROVED",
            )
            .order_by(Capability.name)
        ).all()
        benefits = list(
            db.scalars(
                select(Benefit)
                .where(
                    Benefit.report_id == report.id,
                    Benefit.section_id == section.id,
                    Benefit.approval_state == "APPROVED",
                )
                .order_by(Benefit.created_at)
            ).all()
        )
        operational = source_snapshot.get("operational_sources") or []
        mapping_payload = []
        for mapping, capability in mappings:
            ref = f"mapping:{mapping.id}"
            item = {
                "ref": ref,
                "id": mapping.id,
                "source_ref": mapping.source_ref,
                "source_label": mapping.source_label,
                "source_statement": mapping.source_statement,
                "rationale": mapping.rationale,
                "prerequisites": mapping.prerequisites or capability.typical_prerequisites,
                "capability": {
                    "id": capability.id,
                    "code": capability.capability_code,
                    "name": capability.name,
                    "description": capability.controlled_description,
                    "limitations": capability.limitations,
                    "version": capability.version,
                },
            }
            mapping_payload.append(item)
            all_refs.append({"ref": ref, "label": f"{capability.capability_code} — {capability.name}"})
        benefit_payload = []
        for benefit in benefits:
            ref = f"benefit:{benefit.id}"
            item = {
                "ref": ref,
                "id": benefit.id,
                "statement": benefit.statement,
                "category": benefit.category,
                "measure_type": benefit.measure_type,
                "confidence": benefit.confidence,
            }
            benefit_payload.append(item)
            all_refs.append({"ref": ref, "label": benefit.statement})
        for item in operational:
            all_refs.append({"ref": item.get("ref"), "label": item.get("label") or item.get("ref")})
        solution_payload = None
        if solution:
            solution_payload = {
                "ref": f"solution:{solution.id}",
                "id": solution.id,
                "version": solution.version,
                "text": solution.text,
            }
            all_refs.append({"ref": solution_payload["ref"], "label": f"{section.title} Cloud Inventory approach"})
        section_packets.append({
            "id": section.id,
            "title": section.title,
            "process_module": section.process_module,
            "display_order": section.display_order,
            "section_version": section.version,
            "priority": priority.priority if priority else "OPTIONAL",
            "user_notes": priority.user_notes if priority else "",
            "constraints": priority.constraints if priority else "",
            "estimated_minutes": priority.estimated_minutes if priority else None,
            "operational_sources": operational,
            "solution": solution_payload,
            "approved_mappings": mapping_payload,
            "approved_benefits": benefit_payload,
        })
    current = db.scalar(
        select(DemoPlanVersion)
        .where(DemoPlanVersion.report_id == report.id, DemoPlanVersion.is_current.is_(True))
        .order_by(DemoPlanVersion.version.desc())
    )
    deduped_refs: list[dict[str, Any]] = []
    for item in all_refs:
        if item.get("ref") and not any(row["ref"] == item["ref"] for row in deduped_refs):
            deduped_refs.append(item)
    return {
        "purpose": "DEMO_PLAN",
        "report": {"id": report.id, "title": report.title, "revision": report.revision},
        "settings": {
            "audience": settings.audience if settings else "",
            "duration_minutes": settings.duration_minutes if settings else 45,
            "additional_priorities": settings.additional_priorities if settings else "",
            "version": settings.version if settings else None,
        },
        "sections": section_packets,
        "allowed_source_refs": deduped_refs,
        "current_demo_plan": None if not current else {
            "version": current.version,
            "content": current.content,
            "source_type": current.source_type,
        },
    }


def _normalize_demo_plan(value: Any, snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    raw = value if isinstance(value, dict) else {}
    errors: list[str] = []
    sections = {str(item.get("id")): item for item in snapshot.get("sections") or [] if item.get("id")}
    allowed_refs = {str(item.get("ref")) for item in snapshot.get("allowed_source_refs") or [] if item.get("ref")}
    mapping_to_section: dict[str, str] = {}
    for section in sections.values():
        for mapping in section.get("approved_mappings") or []:
            mapping_to_section[str(mapping.get("id"))] = str(section["id"])
    flow: list[dict[str, Any]] = []
    included_sections: set[str] = set()
    for index, item in enumerate(raw.get("flow") or raw.get("demo_flow") or []):
        if not isinstance(item, dict):
            errors.append(f"Demo flow item {index + 1} was not an object.")
            continue
        section_id = str(item.get("section_id") or "")
        section = sections.get(section_id)
        if not section:
            errors.append(f"Demo flow item {index + 1} references an unknown section.")
            continue
        if section.get("priority") == "DO_NOT_SHOW":
            errors.append(f"Demo flow item {index + 1} includes a section marked DO NOT SHOW.")
            continue
        mapping_ids = [str(value) for value in item.get("capability_mapping_ids") or []]
        mapping_ids = [value for value in mapping_ids if mapping_to_section.get(value) == section_id]
        if not mapping_ids:
            errors.append(f"Demo flow item {index + 1} does not reference an approved capability mapping for its section.")
        source_refs = [str(ref) for ref in item.get("source_refs") or [] if str(ref) in allowed_refs]
        if not source_refs:
            errors.append(f"Demo flow item {index + 1} has no valid source references.")
        included_sections.add(section_id)
        flow.append({
            "sequence": len(flow) + 1,
            "section_id": section_id,
            "operational_area": str(item.get("operational_area") or section.get("title") or "").strip(),
            "priority": section.get("priority") or "OPTIONAL",
            "functionality": str(item.get("functionality") or "").strip(),
            "scenario": str(item.get("scenario") or "").strip(),
            "customer_context": str(item.get("customer_context") or "").strip(),
            "value_statement": str(item.get("value_statement") or "").strip(),
            "sample_data": str(item.get("sample_data") or "").strip(),
            "user_role": str(item.get("user_role") or "").strip(),
            "steps": [str(value).strip() for value in item.get("steps") or [] if str(value).strip()],
            "expected_result": str(item.get("expected_result") or "").strip(),
            "talking_points": [str(value).strip() for value in item.get("talking_points") or [] if str(value).strip()],
            "questions": [str(value).strip() for value in item.get("questions") or [] if str(value).strip()],
            "capability_mapping_ids": mapping_ids,
            "source_refs": source_refs,
            "estimated_minutes": item.get("estimated_minutes") or section.get("estimated_minutes"),
        })
    for section in sections.values():
        if section.get("priority") == "MUST_SHOW" and str(section["id"]) not in included_sections:
            errors.append(f"Must-show operational area '{section.get('title')}' is missing from the demo flow.")
    if not flow:
        errors.append("No valid demo flow items were generated.")
    objectives = [str(value).strip() for value in raw.get("objectives") or [] if str(value).strip()]
    if not objectives:
        errors.append("The demo plan did not include objectives.")
    return {
        "title": str(raw.get("title") or "Cloud Inventory Solution Demonstration Plan").strip(),
        "audience": str(raw.get("audience") or snapshot.get("settings", {}).get("audience") or "").strip(),
        "duration_minutes": int(raw.get("duration_minutes") or snapshot.get("settings", {}).get("duration_minutes") or 45),
        "objectives": objectives,
        "flow": flow,
        "risks_to_avoid": [str(value).strip() for value in raw.get("risks_to_avoid") or raw.get("claims_to_avoid") or [] if str(value).strip()],
        "open_questions": [str(value).strip() for value in raw.get("open_questions") or raw.get("gaps") or [] if str(value).strip()],
        "preparation_notes": [str(value).strip() for value in raw.get("preparation_notes") or [] if str(value).strip()],
    }, errors


def _verify_demo_plan(settings: Settings, snapshot: dict[str, Any], plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "You verify an internal Cloud Inventory demonstration plan. Use only the supplied accepted current-state content, approved capability mappings, approved benefits, and user-entered demo priorities. "
        "Block invented product behavior, unsupported outcomes, guarantees, numeric value claims, ignored MUST_SHOW priorities, included DO_NOT_SHOW areas, or demo steps that are not supported by an approved mapping. "
        "Return only JSON with verification_status (PASSED or BLOCKED) and unsupported_claims."
    )
    result, usage = _call_json(
        settings,
        system=system,
        user_content=json.dumps({"source_packet": snapshot, "proposed_demo_plan": plan}, ensure_ascii=False),
    )
    unsupported = result.get("unsupported_claims") or []
    status = str(result.get("verification_status") or ("BLOCKED" if unsupported else "PASSED")).upper()
    if status not in {"PASSED", "BLOCKED"}:
        status = "BLOCKED" if unsupported else "PASSED"
    return {"verification_status": status, "unsupported_claims": unsupported}, usage


def run_demo_plan(
    settings: Settings,
    snapshot: dict[str, Any],
    instructions: str | None,
    prior_suggestion: AiSuggestion | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    eligible = [
        section for section in snapshot.get("sections") or []
        if section.get("priority") != "DO_NOT_SHOW" and section.get("approved_mappings")
    ]
    if not eligible:
        raise ValueError("Approve at least one capability mapping before generating a demo plan.")
    prior_plan = None
    if prior_suggestion:
        prior_plan = (prior_suggestion.content or {}).get("demo_plan")
    usage_items: list[dict[str, Any]] = []
    system = (
        "You are a senior Cloud Inventory presales consultant creating an internal, customer-specific demonstration plan. "
        "Use only the supplied accepted discovery content, approved capability mappings, approved benefits, user-entered priorities, constraints, audience, and duration. "
        "MUST_SHOW items must be included. DO_NOT_SHOW items must be excluded. Sequence the flow logically and fit the available time. "
        "Each demo item must reference an approved capability mapping and source evidence. Value statements must be contextual and qualitative unless an approved quantitative benefit explicitly supports the number. "
        "Identify functionality not confirmed, dependencies, unresolved questions, and claims the presenter should avoid. "
        "Return only JSON with title, audience, duration_minutes, objectives, flow, risks_to_avoid, open_questions, and preparation_notes. "
        "Each flow item must contain section_id, operational_area, functionality, scenario, customer_context, value_statement, sample_data, user_role, steps, expected_result, talking_points, questions, capability_mapping_ids, source_refs, and estimated_minutes."
    )
    generated, usage = _call_json(
        settings,
        system=system,
        user_content=json.dumps({
            "report": snapshot.get("report"),
            "settings": snapshot.get("settings"),
            "sections": snapshot.get("sections"),
            "current_demo_plan": snapshot.get("current_demo_plan"),
            "prior_ai_plan": prior_plan,
            "user_refinement_instruction": instructions or None,
        }, ensure_ascii=False),
    )
    usage_items.append(usage)
    plan, plan_errors = _normalize_demo_plan(generated, snapshot)
    verification, verify_usage = _verify_demo_plan(settings, snapshot, plan)
    usage_items.append(verify_usage)
    if plan_errors:
        verification["verification_status"] = "BLOCKED"
        verification["unsupported_claims"] = list(verification.get("unsupported_claims") or []) + [
            {"text": "Demo plan validation", "reason": error} for error in plan_errors
        ]
    if verification["verification_status"] == "BLOCKED":
        repair_system = (
            "Repair the demonstration plan using only the same source packet. Include every MUST_SHOW area, exclude every DO_NOT_SHOW area, remove unsupported claims, and reference approved mappings. "
            "Return only the complete JSON demo plan using the original schema."
        )
        repaired, repair_usage = _call_json(
            settings,
            system=repair_system,
            user_content=json.dumps({
                "source_packet": snapshot,
                "proposed_demo_plan": plan,
                "issues": verification.get("unsupported_claims") or [],
            }, ensure_ascii=False),
        )
        usage_items.append(repair_usage)
        repaired_plan, repaired_errors = _normalize_demo_plan(repaired, snapshot)
        if repaired_plan.get("flow"):
            plan = repaired_plan
            verification, verify_usage_2 = _verify_demo_plan(settings, snapshot, plan)
            usage_items.append(verify_usage_2)
            if repaired_errors:
                verification["verification_status"] = "BLOCKED"
                verification["unsupported_claims"] = list(verification.get("unsupported_claims") or []) + [
                    {"text": "Demo plan validation", "reason": error} for error in repaired_errors
                ]
    used_refs: list[str] = []
    for item in plan.get("flow") or []:
        for ref in item.get("source_refs") or []:
            if ref not in used_refs:
                used_refs.append(ref)
    labels = {str(item.get("ref")): item.get("label") or item.get("ref") for item in snapshot.get("allowed_source_refs") or []}
    content = {
        "demo_plan": plan,
        "source_refs": [{"ref": ref, "label": labels.get(ref, ref)} for ref in used_refs],
        "source_snapshot": snapshot,
        "verification_status": verification["verification_status"],
        "unsupported_claims": verification.get("unsupported_claims") or [],
        "accept_allowed": verification["verification_status"] == "PASSED" and bool(plan.get("flow")),
        "refinement_instruction": instructions,
        "parent_suggestion_id": prior_suggestion.id if prior_suggestion else None,
        "source_report_revision": snapshot.get("report", {}).get("revision"),
    }
    return content, _merge_usage(usage_items)



def build_report_quality_snapshot(db: Session, report: Report) -> dict[str, Any]:
    sections = list(
        db.scalars(
            select(ReportSection)
            .where(ReportSection.report_id == report.id, ReportSection.state != "REMOVED")
            .order_by(ReportSection.display_order)
        ).all()
    )
    demo_priorities = {item.section_id: item for item in db.scalars(select(DemoSectionPriority).where(DemoSectionPriority.report_id == report.id)).all()}
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
    section_payload: list[dict[str, Any]] = []
    allowed_refs: list[dict[str, Any]] = []
    for section in sections:
        responses = db.execute(
            select(Response, PromptDefinition)
            .join(PromptDefinition, Response.prompt_id == PromptDefinition.id)
            .where(Response.section_id == section.id, PromptDefinition.active.is_(True))
            .order_by(PromptDefinition.display_order)
        ).all()
        findings = list(db.scalars(select(Finding).where(Finding.report_id == report.id, Finding.section_id == section.id, Finding.status != "REJECTED").order_by(Finding.created_at)).all())
        solution = db.scalar(
            select(SectionContentVersion)
            .where(
                SectionContentVersion.report_id == report.id,
                SectionContentVersion.section_id == section.id,
                SectionContentVersion.content_type == "CLOUD_INVENTORY_APPROACH",
                SectionContentVersion.is_current.is_(True),
            )
            .order_by(SectionContentVersion.version.desc())
        )
        mappings = db.execute(
            select(CapabilityMapping, Capability)
            .join(Capability, CapabilityMapping.capability_id == Capability.id)
            .where(CapabilityMapping.report_id == report.id, CapabilityMapping.section_id == section.id)
            .order_by(Capability.name)
        ).all()
        benefits = list(db.scalars(select(Benefit).where(Benefit.report_id == report.id, Benefit.section_id == section.id).order_by(Benefit.created_at)).all())
        sources: list[dict[str, Any]] = []
        if section.narrative.strip():
            sources.append({"ref": f"section:{section.id}:narrative", "label": f"{section.title} current operations", "text": section.narrative})
        for response, prompt in responses:
            text = response.narrative.strip() or (json.dumps(response.payload, ensure_ascii=False) if response.payload else "")
            if text:
                sources.append({"ref": f"response:{response.id}", "label": f"{section.title} — {prompt.question}", "text": text})
        for finding in findings:
            sources.append({"ref": f"finding:{finding.id}", "label": f"{section.title} — {finding.finding_type.replace('_', ' ').title()}", "text": finding.statement, "impact": finding.impact})
        if solution and solution.text.strip():
            sources.append({"ref": f"solution:{solution.id}", "label": f"{section.title} Cloud Inventory approach", "text": solution.text})
        mapping_payload = []
        for mapping, capability in mappings:
            ref = f"mapping:{mapping.id}"
            mapping_payload.append({
                "ref": ref,
                "approval_state": mapping.approval_state,
                "capability_code": capability.capability_code,
                "capability_name": capability.name,
                "source_ref": mapping.source_ref,
                "rationale": mapping.rationale,
                "prerequisites": mapping.prerequisites or capability.typical_prerequisites,
                "limitations": capability.limitations,
            })
            allowed_refs.append({"ref": ref, "label": f"{capability.capability_code} — {capability.name}"})
        benefit_payload = []
        for benefit in benefits:
            ref = f"benefit:{benefit.id}"
            benefit_payload.append({
                "ref": ref,
                "approval_state": benefit.approval_state,
                "statement": benefit.statement,
                "category": benefit.category,
                "measure_type": benefit.measure_type,
                "source_ref": benefit.source_ref,
                "formula": benefit.formula,
                "assumptions": benefit.assumptions,
            })
            allowed_refs.append({"ref": ref, "label": benefit.statement})
        for source in sources:
            allowed_refs.append({"ref": source["ref"], "label": source["label"]})
        priority = demo_priorities.get(section.id)
        section_payload.append({
            "id": section.id,
            "title": section.title,
            "process_module": section.process_module,
            "version": section.version,
            "sources": sources,
            "mappings": mapping_payload,
            "benefits": benefit_payload,
            "demo_priority": priority.priority if priority else "OPTIONAL",
            "demo_user_notes": priority.user_notes if priority else "",
            "demo_constraints": priority.constraints if priority else "",
            "demo_covered": section.id in demo_section_ids,
        })
    summary = db.scalar(select(ReportContentVersion).where(ReportContentVersion.report_id == report.id, ReportContentVersion.content_type == "EXECUTIVE_SUMMARY", ReportContentVersion.is_current.is_(True)).order_by(ReportContentVersion.version.desc()))
    return {
        "purpose": "REPORT_QUALITY_REVIEW",
        "report": {"id": report.id, "title": report.title, "revision": report.revision, "state": report.state},
        "sections": section_payload,
        "executive_summary": None if not summary else {"id": summary.id, "version": summary.version, "text": summary.text, "source_refs": summary.source_refs},
        "demo_plan": None if not demo_plan else {"version": demo_plan.version, "content": demo_plan.content},
        "allowed_source_refs": allowed_refs,
    }


def _normalize_quality_issues(value: Any, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    valid_sections = {str(item.get("id")): item for item in snapshot.get("sections") or []}
    allowed_refs = {str(item.get("ref")) for item in snapshot.get("allowed_source_refs") or [] if item.get("ref")}
    issues: list[dict[str, Any]] = []
    for raw in value or []:
        if not isinstance(raw, dict):
            continue
        message = str(raw.get("message") or raw.get("issue") or "").strip()
        recommendation = str(raw.get("recommendation") or raw.get("action") or "").strip()
        if not message:
            continue
        section_id = str(raw.get("section_id") or "").strip() or None
        if section_id and section_id not in valid_sections:
            section_id = None
        severity = str(raw.get("severity") or "WARNING").upper()
        if severity not in {"INFO", "WARNING", "ERROR"}:
            severity = "WARNING"
        refs = [str(ref) for ref in raw.get("source_refs") or [] if str(ref) in allowed_refs]
        issues.append({
            "category": str(raw.get("category") or "COMPLETENESS").upper(),
            "severity": severity,
            "section_id": section_id,
            "section_title": valid_sections.get(section_id, {}).get("title") if section_id else None,
            "message": message,
            "recommendation": recommendation,
            "source_refs": refs,
        })
    return issues[:100]


def _verify_quality_review(settings: Settings, snapshot: dict[str, Any], review: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "You verify an AI-generated quality review of a Cloud Inventory discovery report. Use only the supplied report packet. "
        "Block any issue, strength, or recommendation that asserts a customer fact, product behavior, contradiction, omission, or dependency not supported by the packet. "
        "Return only JSON with verification_status (PASSED or BLOCKED) and unsupported_claims."
    )
    result, usage = _call_json(settings, system=system, user_content=json.dumps({"source_packet": snapshot, "proposed_review": review}, ensure_ascii=False))
    unsupported = result.get("unsupported_claims") or []
    status = str(result.get("verification_status") or ("BLOCKED" if unsupported else "PASSED")).upper()
    if status not in {"PASSED", "BLOCKED"}:
        status = "BLOCKED" if unsupported else "PASSED"
    return {"verification_status": status, "unsupported_claims": unsupported}, usage


def run_report_quality_review(settings: Settings, snapshot: dict[str, Any], instructions: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "You are a senior professional-services quality reviewer. Review the complete Cloud Inventory discovery packet for completeness, internal consistency, traceability, unsupported claims, duplicated content, unresolved findings, missing solution coverage, missing benefits, and demo-plan alignment. "
        "General notes are valid observations. Do not invent customer facts or product behavior. Do not rewrite the report. Produce review recommendations only. "
        "Return only JSON with overall_assessment, strengths, issues, and follow_up_questions. Each issue must contain category, severity, section_id when applicable, message, recommendation, and source_refs."
    )
    generated, usage1 = _call_json(settings, system=system, user_content=json.dumps({"source_packet": snapshot, "user_instruction": instructions or None}, ensure_ascii=False))
    review = {
        "overall_assessment": str(generated.get("overall_assessment") or generated.get("summary") or "").strip(),
        "strengths": [str(item).strip() for item in generated.get("strengths") or [] if str(item).strip()],
        "issues": _normalize_quality_issues(generated.get("issues") or [], snapshot),
        "follow_up_questions": [str(item).strip() for item in generated.get("follow_up_questions") or generated.get("questions") or [] if str(item).strip()],
    }
    verification, usage2 = _verify_quality_review(settings, snapshot, review)
    labels = {str(item.get("ref")): item.get("label") or item.get("ref") for item in snapshot.get("allowed_source_refs") or []}
    used_refs: list[str] = []
    for issue in review["issues"]:
        for ref in issue.get("source_refs") or []:
            if ref not in used_refs:
                used_refs.append(ref)
    return {
        **review,
        "source_refs": [{"ref": ref, "label": labels.get(ref, ref)} for ref in used_refs],
        "source_snapshot": snapshot,
        "verification_status": verification["verification_status"],
        "unsupported_claims": verification.get("unsupported_claims") or [],
        "source_report_revision": snapshot.get("report", {}).get("revision"),
    }, _merge_usage([usage1, usage2])


def build_executive_summary_snapshot(db: Session, report: Report) -> dict[str, Any]:
    quality_snapshot = build_report_quality_snapshot(db, report)
    current = db.scalar(select(ReportContentVersion).where(ReportContentVersion.report_id == report.id, ReportContentVersion.content_type == "EXECUTIVE_SUMMARY", ReportContentVersion.is_current.is_(True)).order_by(ReportContentVersion.version.desc()))
    accepted_sections = []
    for section in quality_snapshot.get("sections") or []:
        approved_mappings = [item for item in section.get("mappings") or [] if item.get("approval_state") == "APPROVED"]
        approved_benefits = [item for item in section.get("benefits") or [] if item.get("approval_state") == "APPROVED"]
        accepted_sections.append({
            "id": section.get("id"),
            "title": section.get("title"),
            "process_module": section.get("process_module"),
            "sources": section.get("sources") or [],
            "approved_mappings": approved_mappings,
            "approved_benefits": approved_benefits,
        })
    return {
        "purpose": "EXECUTIVE_SUMMARY",
        "report": quality_snapshot["report"],
        "sections": accepted_sections,
        "demo_plan": quality_snapshot.get("demo_plan"),
        "current_summary": None if not current else {"id": current.id, "version": current.version, "text": current.text},
        "allowed_source_refs": quality_snapshot.get("allowed_source_refs") or [],
    }


def _verify_executive_summary(settings: Settings, snapshot: dict[str, Any], summary_text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "You verify a customer-facing executive summary only against the supplied accepted discovery packet. "
        "Block invented customer facts, unapproved capabilities, unsupported benefits, numerical claims, guarantees, causes, or conclusions. "
        "Neutral synthesis and clearly stated open dependencies are allowed. Return only JSON with verification_status and unsupported_claims."
    )
    result, usage = _call_json(settings, system=system, user_content=json.dumps({"source_packet": snapshot, "proposed_summary": summary_text}, ensure_ascii=False))
    unsupported = result.get("unsupported_claims") or []
    status = str(result.get("verification_status") or ("BLOCKED" if unsupported else "PASSED")).upper()
    if status not in {"PASSED", "BLOCKED"}:
        status = "BLOCKED" if unsupported else "PASSED"
    return {"verification_status": status, "unsupported_claims": unsupported}, usage


def run_executive_summary(settings: Settings, snapshot: dict[str, Any], instructions: str | None, prior_suggestion: AiSuggestion | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    prior_text = ""
    if prior_suggestion:
        prior_text = str((prior_suggestion.content or {}).get("summary_text") or (prior_suggestion.content or {}).get("suggested_text") or "").strip()
    system = (
        "You are a senior Cloud Inventory professional-services writer creating a concise customer-facing executive summary. "
        "Use only the supplied accepted current-state content, approved mappings, approved benefits, accepted demo context, and explicit gaps. "
        "Summarize operational context, principal observations, solution themes, expected qualitative benefits, open dependencies, and recommended next steps. "
        "Do not invent product capabilities, numerical improvements, commitments, or customer facts. Return only JSON with summary_text, source_refs, and gaps."
    )
    generated, usage1 = _call_json(settings, system=system, user_content=json.dumps({
        "source_packet": snapshot,
        "current_summary": snapshot.get("current_summary"),
        "prior_ai_summary": prior_text or None,
        "user_refinement_instruction": instructions or None,
    }, ensure_ascii=False))
    summary_text = str(generated.get("summary_text") or generated.get("suggested_text") or generated.get("summary") or "").strip()
    if not summary_text:
        raise ValueError("AI did not return an executive summary.")
    verification, usage2 = _verify_executive_summary(settings, snapshot, summary_text)
    usage_items = [usage1, usage2]
    if verification["verification_status"] == "BLOCKED":
        repaired, repair_usage = _call_json(settings, system=(
            "Rewrite the executive summary to remove or cautiously rephrase every unsupported claim. Use only the same source packet. Return only JSON with summary_text, source_refs, and gaps."
        ), user_content=json.dumps({"source_packet": snapshot, "proposed_summary": summary_text, "issues": verification.get("unsupported_claims") or []}, ensure_ascii=False))
        usage_items.append(repair_usage)
        repaired_text = str(repaired.get("summary_text") or repaired.get("suggested_text") or "").strip()
        if repaired_text:
            summary_text = repaired_text
            verification, verify_usage2 = _verify_executive_summary(settings, snapshot, summary_text)
            usage_items.append(verify_usage2)
            generated = repaired
    allowed_refs = {str(item.get("ref")) for item in snapshot.get("allowed_source_refs") or [] if item.get("ref")}
    labels = {str(item.get("ref")): item.get("label") or item.get("ref") for item in snapshot.get("allowed_source_refs") or []}
    refs = []
    for raw in generated.get("source_refs") or []:
        ref = str(raw.get("ref") if isinstance(raw, dict) else raw)
        if ref in allowed_refs and ref not in refs:
            refs.append(ref)
    return {
        "summary_text": summary_text,
        "suggested_text": summary_text,
        "gaps": [str(item).strip() for item in generated.get("gaps") or [] if str(item).strip()],
        "source_refs": [{"ref": ref, "label": labels.get(ref, ref)} for ref in refs],
        "source_snapshot": snapshot,
        "verification_status": verification["verification_status"],
        "unsupported_claims": verification.get("unsupported_claims") or [],
        "accept_allowed": verification["verification_status"] == "PASSED",
        "source_report_revision": snapshot.get("report", {}).get("revision"),
        "parent_suggestion_id": prior_suggestion.id if prior_suggestion else None,
    }, _merge_usage(usage_items)


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
    overall_started = time.perf_counter()
    try:
        if job.purpose == "OBSERVATION_ENHANCEMENT":
            if not section:
                raise ValueError("Observation enhancement requires a report section")
            snapshot = dict(job.context_snapshot or {})
            if not snapshot:
                snapshot = build_observation_snapshot(db, report, section, [])
            parent = db.get(AiSuggestion, job.parent_suggestion_id) if job.parent_suggestion_id else None
            if parent and (parent.report_id != report.id or parent.section_id != section.id):
                raise ValueError("Parent AI suggestion does not belong to this report section")

            draft_started = time.perf_counter()
            draft_content, draft_usage = generate_observation_draft(settings, snapshot, job.instructions, parent)
            draft_ms = int((time.perf_counter() - draft_started) * 1000)
            suggestion = db.scalar(
                select(AiSuggestion).where(AiSuggestion.ai_job_id == job.id).order_by(AiSuggestion.created_at.desc())
            )
            if not suggestion:
                suggestion = AiSuggestion(
                    ai_job_id=job.id,
                    report_id=report.id,
                    section_id=job.section_id,
                    purpose=job.purpose,
                    content=draft_content,
                    source_refs=draft_content.get("source_refs", []),
                    confidence="MEDIUM",
                    review_state="PENDING",
                )
                db.add(suggestion)
                db.flush()
            else:
                suggestion.content = draft_content
                suggestion.source_refs = draft_content.get("source_refs", [])
            job.status = "VERIFYING"
            job.token_usage = {
                "stage": "DRAFT_READY",
                "draft": draft_usage,
                "timing_ms": {"draft_generation": draft_ms},
            }
            # Commit the draft so the browser can render it while verification
            # continues in the same fast-text worker lane.
            db.commit()
            db.refresh(suggestion)

            verify_started = time.perf_counter()
            content, verify_usage = finalize_observation_draft(settings, snapshot, draft_content)
            verify_ms = int((time.perf_counter() - verify_started) * 1000)
            suggestion.content = content
            suggestion.source_refs = content.get("source_refs", [])
            suggestion.confidence = "HIGH" if content.get("verification_status") == "PASSED" else "MEDIUM"
            usage = _merge_usage([draft_usage, verify_usage])
            usage["timing_ms"] = {
                "draft_generation": draft_ms,
                "verification_and_repair": verify_ms,
                "total": int((time.perf_counter() - overall_started) * 1000),
            }
        elif job.purpose == "PHOTO_ANALYSIS":
            if not section:
                raise ValueError("Photo analysis requires a report section")
            snapshot = dict(job.context_snapshot or {})
            evidence_id = str(snapshot.get("evidence_id") or "")
            evidence = db.get(EvidenceItem, evidence_id)
            if not evidence or evidence.report_id != report.id or evidence.section_id != section.id:
                raise ValueError("Photo analysis evidence is no longer available in this report section")
            photo_started = time.perf_counter()
            observation, usage = _photo_observation(db, settings, evidence)
            photo_ms = int((time.perf_counter() - photo_started) * 1000)
            usage = dict(usage or {})
            usage["timing_ms"] = {"photo_analysis": photo_ms, "total": photo_ms}
            content = {
                "evidence_id": evidence.id,
                "source_refs": [{"ref": f"evidence:{evidence.id}", "label": "Independent photograph analysis"}],
                "verification_status": "PASSED",
                "accept_allowed": False,
                **observation,
            }
        elif job.purpose == "PHOTO_CONTEXT_REVISION":
            if not section:
                raise ValueError("Photo-context revision requires a report section")
            snapshot = dict(job.context_snapshot or {})
            if not snapshot:
                snapshot = build_photo_context_snapshot(db, report, section, [])
            parent = db.get(AiSuggestion, job.parent_suggestion_id) if job.parent_suggestion_id else None
            if parent and (
                parent.report_id != report.id
                or parent.section_id != section.id
                or parent.purpose != "PHOTO_CONTEXT_REVISION"
            ):
                raise ValueError("Parent photo-context suggestion does not belong to this report section")
            context_started = time.perf_counter()
            content, usage = run_photo_context_revision(settings, snapshot, job.instructions, parent)
            context_ms = int((time.perf_counter() - context_started) * 1000)
            usage = dict(usage or {})
            usage["timing_ms"] = {"photo_context_revision": context_ms, "total": context_ms}
        elif job.purpose == "SOLUTION_APPROACH":
            if not section:
                raise ValueError("Cloud Inventory approach generation requires a report section")
            snapshot = dict(job.context_snapshot or {})
            if not snapshot:
                snapshot = build_solution_snapshot(db, report, section)
            parent = db.get(AiSuggestion, job.parent_suggestion_id) if job.parent_suggestion_id else None
            if parent and (parent.report_id != report.id or parent.section_id != section.id or parent.purpose != "SOLUTION_APPROACH"):
                raise ValueError("Parent solution suggestion does not belong to this report section")
            content, usage = run_solution_approach(settings, snapshot, job.instructions, parent)
        elif job.purpose == "TARGETED_BENEFITS":
            if not section:
                raise ValueError("Targeted benefit generation requires a report section")
            snapshot = dict(job.context_snapshot or {})
            if not snapshot:
                snapshot = build_targeted_benefits_snapshot(db, report, section)
            parent = db.get(AiSuggestion, job.parent_suggestion_id) if job.parent_suggestion_id else None
            if parent and (parent.report_id != report.id or parent.section_id != section.id or parent.purpose != "TARGETED_BENEFITS"):
                raise ValueError("Parent targeted-benefit suggestion does not belong to this report section")
            content, usage = run_targeted_benefits(settings, snapshot, job.instructions, parent)
        elif job.purpose == "DEMO_PLAN":
            snapshot = dict(job.context_snapshot or {})
            if not snapshot:
                snapshot = build_demo_plan_snapshot(db, report)
            parent = db.get(AiSuggestion, job.parent_suggestion_id) if job.parent_suggestion_id else None
            if parent and (parent.report_id != report.id or parent.purpose != "DEMO_PLAN"):
                raise ValueError("Parent demo-plan suggestion does not belong to this report")
            content, usage = run_demo_plan(settings, snapshot, job.instructions, parent)
        elif job.purpose == "REPORT_QUALITY_REVIEW":
            snapshot = dict(job.context_snapshot or {})
            if not snapshot:
                snapshot = build_report_quality_snapshot(db, report)
            content, usage = run_report_quality_review(settings, snapshot, job.instructions)
        elif job.purpose == "EXECUTIVE_SUMMARY":
            snapshot = dict(job.context_snapshot or {})
            if not snapshot:
                snapshot = build_executive_summary_snapshot(db, report)
            parent = db.get(AiSuggestion, job.parent_suggestion_id) if job.parent_suggestion_id else None
            if parent and (parent.report_id != report.id or parent.purpose != "EXECUTIVE_SUMMARY"):
                raise ValueError("Parent executive-summary suggestion does not belong to this report")
            content, usage = run_executive_summary(settings, snapshot, job.instructions, parent)
        else:
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
                confidence="HIGH" if content.get("verification_status") == "PASSED" else "MEDIUM",
                review_state="PENDING",
            )
            db.add(suggestion)
            db.flush()
        else:
            suggestion.content = content
            suggestion.source_refs = content.get("source_refs", [])
            suggestion.confidence = "HIGH" if content.get("verification_status") == "PASSED" else "MEDIUM"
        job.status = "COMPLETED"
        job.token_usage = usage
        job.completed_at = utcnow()
        actor = db.get(User, job.requested_by)
        audit(
            db,
            actor=actor,
            action="AI_SUGGESTION_CREATED",
            target_type="AI_SUGGESTION",
            target_id=suggestion.id,
            prospect_id=report.prospect_id,
            metadata={
                "purpose": job.purpose,
                "ai_job_id": job.id,
                "verification_status": content.get("verification_status"),
                "timing_ms": (usage or {}).get("timing_ms"),
            },
        )
        db.commit()
        db.refresh(suggestion)
        return suggestion
    except Exception as exc:
        job.status = "FAILED"
        job.error = str(exc)[:10000]
        job.completed_at = utcnow()
        db.commit()
        raise
