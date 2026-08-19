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


def _prepare_image_data_url(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((1800, 1800))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        output = io.BytesIO()
        if image.mode == "L":
            image = image.convert("RGB")
        image.save(output, format="JPEG", quality=90, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def process_photo_analysis_job(db: Session, ai_job_id: str, settings) -> dict[str, Any]:
    job = db.get(AiJob, ai_job_id)
    if not job or job.purpose != "PHOTO_ANALYSIS":
        raise ValueError("Photo analysis AI job not found.")
    if job.status == "COMPLETED":
        evidence = db.get(EvidenceItem, (job.context_snapshot or {}).get("evidence_id"))
        return dict((evidence.ai_inclusion_recommendation or {}).get("photo_intelligence") or {}) if evidence else {}

    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    if not decision.allowed:
        job.status = "BLOCKED"
        job.error = decision.reason
        job.completed_at = utcnow()
        db.commit()
        raise ValueError(decision.reason)

    context = dict(job.context_snapshot or {})
    evidence = db.get(EvidenceItem, context.get("evidence_id"))
    if not evidence or evidence.report_id != job.report_id or evidence.section_id != job.section_id:
        raise ValueError("Photo evidence is no longer available in this report section.")
    file_obj = db.scalar(
        select(FileObject)
        .where(FileObject.evidence_id == evidence.id)
        .order_by((FileObject.variant == "ORIGINAL").desc(), FileObject.created_at.asc())
    )
    if not file_obj or not file_obj.mime_type.startswith("image/"):
        raise ValueError("The selected evidence item is not an analyzable image.")

    job.status = "RUNNING"
    job.error = None
    db.commit()

    storage = ObjectStorage(settings)
    data_url = _prepare_image_data_url(storage.get_bytes(file_obj.storage_key))
    system = (
        "Analyze this site-discovery photograph independently. Do not use captions, report narrative, customer notes, or assumptions. "
        "Describe only what is visually supported. Distinguish visible facts from uncertain interpretations. "
        "Return only JSON with: visual_description (string), visible_objects (array), visible_text_or_labels (array), "
        "process_activity (array), operational_observations (array), uncertainties (array), confidence (LOW, MEDIUM, or HIGH)."
    )
    started = time.perf_counter()
    response = _client(
        settings,
        timeout_seconds=float(settings.openai_photo_request_timeout_seconds),
    ).responses.create(
        model=_model(settings, "analysis"),
        store=False,
        input=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Analyze the photograph as independent visual evidence."},
                    {"type": "input_image", "image_url": data_url, "detail": "auto"},
                ],
            },
        ],
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=1400,
    )
    analysis = _parse_json(str(getattr(response, "output_text", "") or ""))
    if not analysis:
        raise ValueError("Photo analysis returned no usable result.")

    file_sha = file_obj.sha256 or context.get("file_sha256") or hashlib.sha256(storage.get_bytes(file_obj.storage_key)).hexdigest()
    result = {
        "schema_version": 1,
        "status": "COMPLETED",
        "file_sha256": file_sha,
        "model": _model(settings, "analysis"),
        "analyzed_at": utcnow().isoformat(),
        "analysis": analysis,
        "usage": _usage(response),
        "timing_ms": {"analysis": int((time.perf_counter() - started) * 1000)},
    }
    metadata = dict(evidence.ai_inclusion_recommendation or {})
    metadata["photo_intelligence"] = result
    evidence.ai_inclusion_recommendation = metadata
    job.status = "COMPLETED"
    job.token_usage = {"analysis": result["usage"], "timing_ms": result["timing_ms"]}
    job.completed_at = utcnow()
    job.error = None

    report = db.get(Report, job.report_id)
    actor = db.get(User, job.requested_by)
    audit(
        db,
        actor=actor,
        action="PHOTO_INTELLIGENCE_ANALYZED",
        target_type="EVIDENCE",
        target_id=evidence.id,
        prospect_id=report.prospect_id if report else None,
        metadata={"ai_job_id": job.id, "file_sha256": file_sha, "model": _model(settings, "analysis")},
    )
    db.commit()
    return result


def _verify_photo_revision(
    settings,
    *,
    snapshot: dict[str, Any],
    proposed_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    system = (
        "Verify that every factual statement in the proposed revised Current Operations Narrative is supported by either "
        "the original written narrative or the supplied independent photo analyses. Do not use external knowledge and do not strengthen "
        "uncertain visual interpretations into facts. Return only JSON with verification_status (PASSED or BLOCKED) and unsupported_claims."
    )
    response = _client(
        settings,
        timeout_seconds=float(settings.openai_request_timeout_seconds),
    ).responses.create(
        model=_model(settings, "analysis"),
        store=False,
        input=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "original_narrative": snapshot.get("original_narrative"),
                        "photo_analyses": snapshot.get("photos") or [],
                        "proposed_text": proposed_text,
                    },
                    ensure_ascii=False,
                ),
            },
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


def process_photo_revision_job(db: Session, ai_job_id: str, settings) -> AiSuggestion:
    job = db.get(AiJob, ai_job_id)
    if not job or job.purpose != "PHOTO_CONTEXT_REVISION":
        raise ValueError("Photo-context revision AI job not found.")
    existing = db.scalar(
        select(AiSuggestion).where(AiSuggestion.ai_job_id == job.id).order_by(AiSuggestion.created_at.desc())
    )
    if existing and job.status == "COMPLETED":
        return existing

    decision = evaluate_policy(settings, contains_prospect_confidential_content=True)
    if not decision.allowed:
        job.status = "BLOCKED"
        job.error = decision.reason
        job.completed_at = utcnow()
        db.commit()
        raise ValueError(decision.reason)

    snapshot = dict(job.context_snapshot or {})
    original = str(snapshot.get("original_narrative") or "").strip()
    if not original:
        raise ValueError("Enter Current Operations Narrative content before correlating photographs.")

    job.status = "RUNNING"
    job.error = None
    db.commit()

    system = (
        "You are correlating independently generated photo analyses with a written Current Operations Narrative. "
        "The photo analyses were produced without narrative context; preserve that independence. Now use the written narrative only to "
        "understand operational context and determine whether the narrative should be revised. Do not invent facts, causes, frequencies, "
        "performance claims, recommendations, benefits, or product capabilities. Preserve user-selected Observation, Pain Point, Risk, Gap, "
        "Strength, and Opportunity headings. Return only JSON with revision_needed (boolean), suggested_text (string), "
        "photo_supported_additions (array), conflicts_or_questions (array), and rationale (string)."
    )
    started = time.perf_counter()
    response = _client(
        settings,
        timeout_seconds=float(settings.openai_photo_request_timeout_seconds),
    ).responses.create(
        model=_model(settings, "analysis"),
        store=False,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)},
        ],
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=1800,
    )
    generated = _parse_json(str(getattr(response, "output_text", "") or ""))
    suggested_text = str(generated.get("suggested_text") or "").strip()
    revision_needed = bool(generated.get("revision_needed", bool(suggested_text and suggested_text != original)))
    if not suggested_text:
        suggested_text = original

    verification, verify_usage = _verify_photo_revision(
        settings,
        snapshot=snapshot,
        proposed_text=suggested_text,
    )
    refs = [{"ref": "section:narrative", "label": "Current Operations Narrative"}]
    refs.extend(
        {
            "ref": f"evidence:{photo.get('evidence_id')}",
            "label": str(photo.get("caption") or "Site photograph"),
        }
        for photo in snapshot.get("photos") or []
        if photo.get("evidence_id")
    )
    content = {
        "original_text": original,
        "enhanced_text": suggested_text,
        "suggested_text": suggested_text,
        "revision_needed": revision_needed,
        "photo_supported_additions": generated.get("photo_supported_additions") or [],
        "conflicts_or_questions": generated.get("conflicts_or_questions") or [],
        "rationale": generated.get("rationale") or "",
        "photo_observations": snapshot.get("photos") or [],
        "source_snapshot": snapshot,
        "source_refs": refs,
        "source_section_version": snapshot.get("source_section_version"),
        "source_narrative_fingerprint": snapshot.get("source_narrative_fingerprint"),
        "verification_status": verification["verification_status"],
        "unsupported_claims": verification["unsupported_claims"],
        "accept_allowed": verification["verification_status"] == "PASSED" and revision_needed,
        "workflow_stage": "COMPLETED",
    }
    suggestion = existing or AiSuggestion(
        ai_job_id=job.id,
        report_id=job.report_id,
        section_id=job.section_id,
        purpose="PHOTO_CONTEXT_REVISION",
        content=content,
        source_refs=refs,
        confidence="HIGH" if content["accept_allowed"] else "MEDIUM",
        review_state="PENDING",
        source_fingerprint=job.source_fingerprint,
    )
    if existing:
        suggestion.content = content
        suggestion.source_refs = refs
        suggestion.confidence = "HIGH" if content["accept_allowed"] else "MEDIUM"
        suggestion.source_fingerprint = job.source_fingerprint
    else:
        db.add(suggestion)
        db.flush()

    for prior in db.scalars(
        select(AiSuggestion).where(
            AiSuggestion.report_id == job.report_id,
            AiSuggestion.section_id == job.section_id,
            AiSuggestion.purpose == "PHOTO_CONTEXT_REVISION",
            AiSuggestion.id != suggestion.id,
            AiSuggestion.review_state == "PENDING",
        )
    ).all():
        prior.review_state = "SUPERSEDED"
        prior.superseded_by_suggestion_id = suggestion.id

    job.status = "COMPLETED"
    job.token_usage = {
        "generation": _usage(response),
        "verification": verify_usage,
        "timing_ms": {"total": int((time.perf_counter() - started) * 1000)},
    }
    job.completed_at = utcnow()
    job.error = None

    report = db.get(Report, job.report_id)
    actor = db.get(User, job.requested_by)
    audit(
        db,
        actor=actor,
        action="PHOTO_CONTEXT_REVISION_CREATED",
        target_type="AI_SUGGESTION",
        target_id=suggestion.id,
        prospect_id=report.prospect_id if report else None,
        metadata={
            "ai_job_id": job.id,
            "verification_status": content["verification_status"],
            "revision_needed": revision_needed,
        },
    )
    db.commit()
    db.refresh(suggestion)
    return suggestion
