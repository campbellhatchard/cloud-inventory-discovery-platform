from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from typing import Any

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_service import evaluate_policy
from .audit import audit
from .jobs import enqueue
from .models import AiJob, AiSuggestion, EvidenceItem, FileObject, Report, ReportSection, User, utcnow
from .storage import ObjectStorage


def _model(settings, kind: str) -> str:
    if kind == "fast":
        return settings.openai_fast_text_model or settings.openai_model
    return settings.openai_analysis_model or settings.openai_model


def _client(settings, *, timeout_seconds: float):
    from openai import OpenAI  # type: ignore

    kwargs: dict[str, Any] = {
        "api_key": settings.openai_api_key,
        "timeout": timeout_seconds,
        "max_retries": 0,
    }
    if settings.openai_project_id:
        kwargs["project"] = settings.openai_project_id
    return OpenAI(**kwargs)


def _usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    return usage.model_dump() if hasattr(usage, "model_dump") else {}


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
        value = json.loads(candidate)
        return value if isinstance(value, dict) else {"value": value}
    except json.JSONDecodeError:
        return {"text": candidate}


def _written_sources(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in snapshot.get("sources") or [] if item.get("type") != "PHOTO"]


def _source_refs(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"ref": str(item.get("ref")), "label": str(item.get("label") or item.get("ref"))}
        for item in _written_sources(snapshot)
        if item.get("ref")
    ]


def _supersede_prior_observation_suggestions(
    db: Session,
    suggestion: AiSuggestion,
    source_fingerprint: str,
) -> None:
    prior_items = list(
        db.scalars(
            select(AiSuggestion)
            .where(
                AiSuggestion.report_id == suggestion.report_id,
                AiSuggestion.section_id == suggestion.section_id,
                AiSuggestion.purpose == "OBSERVATION_ENHANCEMENT",
                AiSuggestion.id != suggestion.id,
                AiSuggestion.review_state == "PENDING",
            )
            .order_by(AiSuggestion.created_at.desc())
        ).all()
    )
    for prior in prior_items:
        prior_fingerprint = str(prior.source_fingerprint or (prior.content or {}).get("source_fingerprint") or "")
        prior.review_state = "SUPERSEDED" if prior_fingerprint == source_fingerprint else "STALE"
        prior.superseded_by_suggestion_id = suggestion.id


def _call_fast_wording(
    settings,
    *,
    snapshot: dict[str, Any],
    instructions: str | None,
    prior_text: str | None,
) -> tuple[str, dict[str, Any]]:
    sources = _written_sources(snapshot)
    if not sources:
        raise ValueError("Enter Current Operations Narrative content before requesting AI wording.")

    if prior_text:
        system = (
            "Edit the supplied base AI wording according to the refinement request. "
            "Use the written source material only as factual authority. Preserve user-selected headings such as "
            "Observation:, Pain Point:, Risk:, Gap:, Strength:, and Opportunity:. Do not add recommendations, benefits, "
            "root causes, frequencies, performance claims, or numbers unless they are explicitly present in the sources. "
            "Do not analyze or infer from photographs. Return only the revised narrative text with no preamble, JSON, or markdown fences."
        )
    else:
        system = (
            "Rewrite the supplied current-operations discovery notes into concise professional customer-facing wording. "
            "Use only the written facts supplied. Preserve uncertainty and user-selected headings such as Observation:, "
            "Pain Point:, Risk:, Gap:, Strength:, and Opportunity:. Do not add recommendations, benefits, root causes, "
            "frequencies, performance claims, or numbers unless explicitly present. Do not analyze or infer from photographs. "
            "Return only the revised narrative text with no preamble, JSON, or markdown fences."
        )

    payload = {
        "section": {
            "title": (snapshot.get("section") or {}).get("title"),
            "process_module": (snapshot.get("section") or {}).get("process_module"),
        },
        "written_sources": sources,
        "base_ai_wording": prior_text or None,
        "refinement_request": (instructions or "").strip() or None,
    }
    started = time.perf_counter()
    response = _client(
        settings,
        timeout_seconds=float(settings.openai_request_timeout_seconds),
    ).responses.create(
        model=_model(settings, "fast"),
        store=False,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=1200,
    )
    text = str(getattr(response, "output_text", "") or "").strip()
    if not text:
        raise ValueError("AI did not return enhanced observation text.")
    usage = _usage(response)
    usage["timing_ms"] = {"draft_generation": int((time.perf_counter() - started) * 1000)}
    return text, usage


def process_fast_wording_job(db: Session, ai_job_id: str, settings) -> AiSuggestion:
    job = db.get(AiJob, ai_job_id)
    if not job or job.purpose != "OBSERVATION_ENHANCEMENT":
        raise ValueError("Fast wording AI job not found.")
    existing = db.scalar(
        select(AiSuggestion).where(AiSuggestion.ai_job_id == job.id).order_by(AiSuggestion.created_at.desc())
    )
    if existing and job.status in {"VERIFYING", "COMPLETED"}:
        return existing

    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    if not decision.allowed:
        job.status = "BLOCKED"
        job.policy_decision = decision.as_dict()
        job.error = decision.reason
        job.completed_at = utcnow()
        db.commit()
        raise ValueError(decision.reason)

    report = db.get(Report, job.report_id)
    section = db.get(ReportSection, job.section_id) if job.section_id else None
    if not report or not section or section.report_id != report.id:
        raise ValueError("Fast wording report section is no longer available.")

    snapshot = dict(job.context_snapshot or {})
    prior = db.get(AiSuggestion, job.parent_suggestion_id) if job.parent_suggestion_id else None
    prior_text = None
    if prior:
        if prior.report_id != report.id or prior.section_id != section.id or prior.purpose != "OBSERVATION_ENHANCEMENT":
            raise ValueError("Parent AI wording does not belong to this report section.")
        prior_text = str((prior.content or {}).get("enhanced_text") or (prior.content or {}).get("suggested_text") or "").strip()
        if not prior_text:
            raise ValueError("The parent AI wording does not contain text that can be refined.")

    job.status = "RUNNING"
    job.error = None
    db.commit()

    enhanced_text, draft_usage = _call_fast_wording(
        settings,
        snapshot=snapshot,
        instructions=job.instructions,
        prior_text=prior_text,
    )
    fingerprint = str(job.source_fingerprint or snapshot.get("source_fingerprint") or "")
    refs = _source_refs(snapshot)
    content = {
        "original_text": str((snapshot.get("section") or {}).get("original_narrative") or ""),
        "source_snapshot": snapshot,
        "source_fingerprint": fingerprint,
        "enhanced_text": enhanced_text,
        "suggested_text": enhanced_text,
        "base_ai_text": prior_text,
        "change_summary": [],
        "gaps": [],
        "claims": [],
        "source_refs": refs,
        "photo_observations": [],
        "verification_status": "VERIFYING",
        "unsupported_claims": [],
        "accept_allowed": False,
        "refinement_instruction": (job.instructions or "").strip() or None,
        "parent_suggestion_id": prior.id if prior else None,
        "source_section_version": (snapshot.get("section") or {}).get("version"),
        "workflow_stage": "DRAFT_READY",
    }

    suggestion = existing or AiSuggestion(
        ai_job_id=job.id,
        report_id=report.id,
        section_id=section.id,
        purpose="OBSERVATION_ENHANCEMENT",
        content=content,
        source_refs=refs,
        confidence="MEDIUM",
        review_state="PENDING",
        source_fingerprint=fingerprint or None,
        parent_suggestion_id=prior.id if prior else None,
        base_ai_text=prior_text,
        refinement_instruction=(job.instructions or "").strip() or None,
    )
    if existing:
        suggestion.content = content
        suggestion.source_refs = refs
        suggestion.source_fingerprint = fingerprint or None
        suggestion.parent_suggestion_id = prior.id if prior else None
        suggestion.base_ai_text = prior_text
        suggestion.refinement_instruction = (job.instructions or "").strip() or None
    else:
        db.add(suggestion)
        db.flush()

    _supersede_prior_observation_suggestions(db, suggestion, fingerprint)
    job.status = "VERIFYING"
    job.token_usage = {"stage": "DRAFT_READY", "draft": draft_usage}
    db.flush()
    enqueue(
        db,
        "ai.verify-observation",
        {"ai_job_id": job.id, "suggestion_id": suggestion.id},
        max_attempts=3,
        queue_name="AI_VERIFICATION",
        priority=20,
    )
    actor = db.get(User, job.requested_by)
    audit(
        db,
        actor=actor,
        action="AI_FAST_WORDING_DRAFT_READY",
        target_type="AI_SUGGESTION",
        target_id=suggestion.id,
        prospect_id=report.prospect_id,
        metadata={
            "ai_job_id": job.id,
            "model": _model(settings, "fast"),
            "timing_ms": draft_usage.get("timing_ms"),
        },
    )
    db.commit()
    db.refresh(suggestion)
    return suggestion


def _verify_observation(
    settings,
    *,
    snapshot: dict[str, Any],
    proposed_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "Verify the proposed Current Operations Narrative only against the supplied written sources. "
        "A claim is unsupported if it adds a customer fact, process step, cause, frequency, performance claim, numeric value, "
        "or certainty that is absent from the sources. Grammar and neutral transitions are allowed. "
        "Return only JSON with verification_status (PASSED or BLOCKED) and unsupported_claims, an array of objects with text and reason."
    )
    payload = {"sources": _written_sources(snapshot), "proposed_text": proposed_text}
    response = _client(
        settings,
        timeout_seconds=float(settings.openai_request_timeout_seconds),
    ).responses.create(
        model=_model(settings, "analysis"),
        store=False,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=900,
    )
    parsed = _parse_json(str(getattr(response, "output_text", "") or ""))
    unsupported = parsed.get("unsupported_claims") or []
    status = str(parsed.get("verification_status") or ("BLOCKED" if unsupported else "PASSED")).upper()
    if status not in {"PASSED", "BLOCKED"}:
        status = "BLOCKED" if unsupported else "PASSED"
    return {"verification_status": status, "unsupported_claims": unsupported}, _usage(response)


def _repair_observation(
    settings,
    *,
    snapshot: dict[str, Any],
    proposed_text: str,
    unsupported_claims: list[Any],
) -> tuple[str, dict[str, Any]]:
    system = (
        "Repair the proposed Current Operations Narrative by removing or cautiously rephrasing every unsupported claim. "
        "Use only the supplied written sources. Preserve user-selected Observation, Pain Point, Risk, Gap, Strength, and Opportunity headings. "
        "Return only the repaired narrative text with no preamble, JSON, or markdown fences."
    )
    payload = {
        "sources": _written_sources(snapshot),
        "proposed_text": proposed_text,
        "unsupported_claims": unsupported_claims,
    }
    response = _client(
        settings,
        timeout_seconds=float(settings.openai_request_timeout_seconds),
    ).responses.create(
        model=_model(settings, "analysis"),
        store=False,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=1200,
    )
    repaired = str(getattr(response, "output_text", "") or "").strip()
    return repaired or proposed_text, _usage(response)


def process_observation_verification_job(
    db: Session,
    ai_job_id: str,
    suggestion_id: str,
    settings,
) -> AiSuggestion:
    job = db.get(AiJob, ai_job_id)
    suggestion = db.get(AiSuggestion, suggestion_id)
    if not job or not suggestion or suggestion.ai_job_id != job.id:
        raise ValueError("Observation verification target is no longer available.")
    if job.status == "COMPLETED":
        return suggestion

    content = dict(suggestion.content or {})
    snapshot = dict(content.get("source_snapshot") or job.context_snapshot or {})
    enhanced_text = str(content.get("enhanced_text") or "").strip()
    if not enhanced_text:
        raise ValueError("The fast wording draft is empty.")

    started = time.perf_counter()
    verification, verify_usage = _verify_observation(
        settings,
        snapshot=snapshot,
        proposed_text=enhanced_text,
    )
    repair_usage: dict[str, Any] | None = None
    reverify_usage: dict[str, Any] | None = None

    if verification["verification_status"] == "BLOCKED" and verification["unsupported_claims"]:
        enhanced_text, repair_usage = _repair_observation(
            settings,
            snapshot=snapshot,
            proposed_text=enhanced_text,
            unsupported_claims=verification["unsupported_claims"],
        )
        verification, reverify_usage = _verify_observation(
            settings,
            snapshot=snapshot,
            proposed_text=enhanced_text,
        )

    content.update(
        {
            "enhanced_text": enhanced_text,
            "suggested_text": enhanced_text,
            "verification_status": verification["verification_status"],
            "unsupported_claims": verification["unsupported_claims"],
            "accept_allowed": verification["verification_status"] == "PASSED",
            "workflow_stage": "COMPLETED",
        }
    )
    suggestion.content = content
    suggestion.confidence = "HIGH" if content["accept_allowed"] else "MEDIUM"
    job.status = "COMPLETED"
    previous = dict(job.token_usage or {})
    job.token_usage = {
        **previous,
        "stage": "COMPLETED",
        "verification": verify_usage,
        "repair": repair_usage,
        "reverification": reverify_usage,
        "timing_ms": {
            **dict((previous.get("draft") or {}).get("timing_ms") or {}),
            "verification_total": int((time.perf_counter() - started) * 1000),
        },
    }
    job.completed_at = utcnow()
    job.error = None

    report = db.get(Report, job.report_id)
    actor = db.get(User, job.requested_by)
    audit(
        db,
        actor=actor,
        action="AI_FAST_WORDING_VERIFIED",
        target_type="AI_SUGGESTION",
        target_id=suggestion.id,
        prospect_id=report.prospect_id if report else None,
        metadata={
            "ai_job_id": job.id,
            "verification_status": content["verification_status"],
            "model": _model(settings, "analysis"),
        },
    )
    db.commit()
    db.refresh(suggestion)
    return suggestion

