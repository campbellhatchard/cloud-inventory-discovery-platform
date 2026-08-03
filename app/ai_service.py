from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .audit import audit
from .config import Settings
from .models import (
    AiJob,
    AiSuggestion,
    Capability,
    EvidenceAiObservation,
    EvidenceItem,
    FileObject,
    Finding,
    KnowledgeEntry,
    Metric,
    PromptDefinition,
    Report,
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


def _call_json(settings: Settings, *, system: str, user_content: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    client = _client(settings)
    response = client.responses.create(
        model=settings.openai_model,
        store=False,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )
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


def _photo_observation(
    db: Session,
    settings: Settings,
    evidence: EvidenceItem,
) -> tuple[dict[str, Any], dict[str, Any]]:
    file_obj = _image_file(db, evidence.id)
    if not file_obj:
        return {
            "visible_observations": [],
            "operational_interpretations": [],
            "uncertainties": ["The selected evidence item is not an image and was not visually analyzed."],
        }, {}

    cached = db.scalar(select(EvidenceAiObservation).where(EvidenceAiObservation.evidence_id == evidence.id))
    if cached and cached.source_file_sha256 == file_obj.sha256:
        return dict(cached.content), {"cached": True}

    storage = ObjectStorage(settings)
    image_bytes = storage.get_bytes(file_obj.storage_key)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    system = (
        "You are analyzing a site-walk photograph as evidence for a professional operations discovery report. "
        "Describe only what is visibly supportable. You may offer cautious operational interpretations only when the visual evidence supports them. "
        "Do not infer identity, personal characteristics, company policy, process frequency, performance, financial impact, root cause, or hidden system behavior. "
        "If an interpretation is uncertain, put it in uncertainties instead of presenting it as fact. "
        "Return only JSON with keys visible_observations, operational_interpretations, uncertainties. Each value must be an array of short strings."
    )
    prompt = (
        f"Evidence reference: evidence:{evidence.id}\n"
        f"Caption supplied by user: {evidence.caption or 'None'}\n"
        "Analyze this photograph for operationally relevant observations."
    )
    user_content = [
        {"type": "input_text", "text": prompt},
        {
            "type": "input_image",
            "image_url": f"data:{file_obj.mime_type};base64,{encoded}",
            "detail": "auto",
        },
    ]
    content, usage = _call_json(settings, system=system, user_content=user_content)
    normalized = {
        "visible_observations": [str(item) for item in content.get("visible_observations") or []],
        "operational_interpretations": [str(item) for item in content.get("operational_interpretations") or []],
        "uncertainties": [str(item) for item in content.get("uncertainties") or []],
    }
    if cached:
        cached.model = settings.openai_model
        cached.source_file_sha256 = file_obj.sha256
        cached.content = normalized
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
    return normalized, usage


def _merge_usage(items: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": len(items)}
    for item in items:
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = item.get(key)
            if isinstance(value, int):
                totals[key] += value
    totals["details"] = items
    return totals


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
        "You are a factual-support verifier. Evaluate the proposed customer-facing current-operations narrative only against the supplied source packet. "
        "Do not use external knowledge. A sentence is unsupported if it adds a customer fact, process step, frequency, cause, performance claim, numeric value, or certainty not present in the source packet. "
        "Reasonable grammar, neutral transitions, and cautious wording are allowed. Return only JSON with keys verification_status and unsupported_claims. "
        "verification_status must be PASSED when every factual claim is supported, otherwise BLOCKED. unsupported_claims must be an array of objects with text and reason."
    )
    payload = {
        "sources": snapshot.get("sources") or [],
        "photo_observations": photo_observations,
        "proposed_text": enhanced_text,
    }
    result, usage = _call_json(settings, system=system, user_content=json.dumps(payload, ensure_ascii=False))
    unsupported = result.get("unsupported_claims") or []
    status = str(result.get("verification_status") or ("BLOCKED" if unsupported else "PASSED")).upper()
    if status not in {"PASSED", "BLOCKED"}:
        status = "BLOCKED" if unsupported else "PASSED"
    return {"verification_status": status, "unsupported_claims": unsupported}, usage


def run_observation_enhancement(
    db: Session,
    settings: Settings,
    snapshot: dict[str, Any],
    instructions: str | None,
    prior_suggestion: AiSuggestion | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    usage_items: list[dict[str, Any]] = []
    photo_observations: list[dict[str, Any]] = []
    for evidence_id in snapshot.get("selected_evidence_ids") or []:
        evidence = db.get(EvidenceItem, evidence_id)
        if not evidence or evidence.report_id != snapshot["report"]["id"] or evidence.section_id != snapshot["section"]["id"]:
            continue
        observation, usage = _photo_observation(db, settings, evidence)
        if usage:
            usage_items.append(usage)
        photo_observations.append(
            {
                "ref": f"evidence:{evidence.id}",
                "caption": evidence.caption,
                **observation,
            }
        )

    prior_text = ""
    if prior_suggestion:
        prior_text = str((prior_suggestion.content or {}).get("enhanced_text") or (prior_suggestion.content or {}).get("suggested_text") or "").strip()

    system = (
        "You are a senior professional-services editor improving a site-discovery description of the customer's CURRENT operation. "
        "Use only the supplied user-entered source material and supplied photo observations. Do not use external knowledge. "
        "Do not add Cloud Inventory solution language, recommendations, benefits, root causes, process frequencies, financial impacts, performance claims, or numeric values unless explicitly present in a source. "
        "Preserve uncertainty and neutral professional tone. Photo interpretations must be phrased cautiously unless directly visible. "
        "The result will be reviewed by the customer and professional services team. "
        "Return only JSON with keys enhanced_text, change_summary, gaps, source_refs, claims. "
        "source_refs is an array of source reference strings. claims is an array of objects with text and source_refs. Every factual claim must cite at least one supplied source reference."
    )
    request_payload = {
        "section": snapshot.get("section"),
        "source_material": snapshot.get("sources") or [],
        "photo_observations": photo_observations,
        "user_refinement_instruction": instructions or None,
        "prior_enhanced_text": prior_text or None,
    }
    generated, usage = _call_json(settings, system=system, user_content=json.dumps(request_payload, ensure_ascii=False))
    usage_items.append(usage)
    enhanced_text = str(generated.get("enhanced_text") or generated.get("suggested_text") or "").strip()
    if not enhanced_text:
        raise ValueError("AI did not return enhanced observation text.")

    verification, verify_usage = _verify_observation_text(settings, snapshot, photo_observations, enhanced_text)
    usage_items.append(verify_usage)

    # One controlled repair attempt removes unsupported claims instead of asking
    # the reviewer to identify hallucinations manually.
    if verification["verification_status"] == "BLOCKED" and verification["unsupported_claims"]:
        repair_system = (
            "Rewrite the proposed current-operations narrative to remove or cautiously rephrase every unsupported claim identified by the verifier. "
            "Use only the supplied sources and photo observations. Do not add new facts. Return only JSON with key enhanced_text."
        )
        repair_payload = {
            "sources": snapshot.get("sources") or [],
            "photo_observations": photo_observations,
            "proposed_text": enhanced_text,
            "unsupported_claims": verification["unsupported_claims"],
        }
        repaired, repair_usage = _call_json(settings, system=repair_system, user_content=json.dumps(repair_payload, ensure_ascii=False))
        usage_items.append(repair_usage)
        repaired_text = str(repaired.get("enhanced_text") or "").strip()
        if repaired_text:
            enhanced_text = repaired_text
            verification, verify_usage_2 = _verify_observation_text(settings, snapshot, photo_observations, enhanced_text)
            usage_items.append(verify_usage_2)

    allowed = _allowed_source_refs(snapshot)
    source_refs = _normalize_source_refs(generated.get("source_refs"), allowed)
    if not source_refs:
        # Source labels are a traceability aid, not a factual substitute. When
        # the model omits the array, show the full evidence set actually used.
        source_refs = [
            {"ref": str(item["ref"]), "label": str(item.get("label") or item["ref"])}
            for item in snapshot.get("sources") or []
            if item.get("ref")
        ]

    content = {
        "original_text": str(snapshot.get("section", {}).get("original_narrative") or ""),
        "source_snapshot": snapshot,
        "enhanced_text": enhanced_text,
        "suggested_text": enhanced_text,
        "change_summary": generated.get("change_summary") or [],
        "gaps": generated.get("gaps") or [],
        "claims": generated.get("claims") or [],
        "source_refs": source_refs,
        "photo_observations": photo_observations,
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
        if job.purpose == "OBSERVATION_ENHANCEMENT":
            if not section:
                raise ValueError("Observation enhancement requires a report section")
            snapshot = dict(job.context_snapshot or {})
            if not snapshot:
                snapshot = build_observation_snapshot(db, report, section, [])
            parent = db.get(AiSuggestion, job.parent_suggestion_id) if job.parent_suggestion_id else None
            if parent and (parent.report_id != report.id or parent.section_id != section.id):
                raise ValueError("Parent AI suggestion does not belong to this report section")
            content, usage = run_observation_enhancement(db, settings, snapshot, job.instructions, parent)
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
