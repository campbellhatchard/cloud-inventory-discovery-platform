from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Job, utcnow


def enqueue(db: Session, job_type: str, payload: dict[str, Any], *, max_attempts: int = 5) -> Job:
    job = Job(job_type=job_type, payload=payload, max_attempts=max_attempts)
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session, worker_id: str) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.status == "QUEUED", Job.available_at <= utcnow())
        .order_by(Job.created_at)
        .limit(1)
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = db.scalar(stmt)
    if not job:
        db.rollback()
        return None
    job.status = "RUNNING"
    job.locked_at = utcnow()
    job.locked_by = worker_id
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def complete(db: Session, job: Job) -> None:
    job.status = "COMPLETED"
    job.completed_at = utcnow()
    job.error = None
    db.commit()


def fail(db: Session, job: Job, error: str) -> None:
    job.error = error[:10000]
    if job.attempts >= job.max_attempts:
        job.status = "FAILED"
    else:
        job.status = "QUEUED"
        job.available_at = utcnow() + timedelta(seconds=min(300, 2 ** job.attempts * 5))
        job.locked_at = None
        job.locked_by = None
    db.commit()
