from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditEvent, User


def audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    prospect_id: str | None = None,
    request_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=actor.id if actor else None,
            prospect_id=prospect_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            event_metadata=metadata or {},
        )
    )
