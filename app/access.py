from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import user_roles
from .models import ProspectMembership, Report, ReportMember, User

ROLE_RANK = {"CONTRIBUTOR": 10, "REVIEWER": 20, "OWNER": 30, "ADMIN": 100}


def is_admin(db: Session, user: User) -> bool:
    return "ADMIN" in user_roles(db, user.id)


def prospect_scope(db: Session, user: User, prospect_id: str) -> str | None:
    if is_admin(db, user):
        return "ADMIN"
    membership = db.get(ProspectMembership, (prospect_id, user.id))
    return membership.role_scope if membership else None


def require_prospect_access(db: Session, user: User, prospect_id: str, minimum: str = "CONTRIBUTOR") -> str:
    scope = prospect_scope(db, user, prospect_id)
    if not scope or ROLE_RANK.get(scope, 0) < ROLE_RANK.get(minimum, 0):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Prospect access denied.")
    return scope


def report_scope(db: Session, user: User, report: Report) -> str | None:
    if is_admin(db, user):
        return "ADMIN"
    if report.owner_id == user.id:
        return "OWNER"
    member = db.get(ReportMember, (report.id, user.id))
    if member:
        return member.role_scope
    return prospect_scope(db, user, report.prospect_id)


def require_report_access(db: Session, user: User, report: Report, minimum: str = "CONTRIBUTOR") -> str:
    scope = report_scope(db, user, report)
    if not scope or ROLE_RANK.get(scope, 0) < ROLE_RANK.get(minimum, 0):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Report access denied.")
    return scope


def accessible_prospect_ids(db: Session, user: User) -> list[str] | None:
    if is_admin(db, user):
        return None
    return list(db.scalars(select(ProspectMembership.prospect_id).where(ProspectMembership.user_id == user.id)).all())
