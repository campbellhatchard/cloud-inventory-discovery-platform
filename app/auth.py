from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db
from .models import User, UserRole, UserSession, utcnow
from .usernames import normalize_username



def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User, request: Request, settings: Settings) -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    session = UserSession(
        user_id=user.id,
        token_hash=session_token_hash(raw_token),
        csrf_token=csrf_token,
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
        user_agent=(request.headers.get("user-agent") or "")[:2000],
    )
    db.add(session)
    db.commit()
    return raw_token, csrf_token


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username_key == normalize_username(username)))
    if not user or user.status != "ACTIVE":
        return None
    now = utcnow()
    if user.locked_until and _aware(user.locked_until) > now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked.")
    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= LOCKOUT_THRESHOLD:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
        db.commit()
        return None
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    return user


def get_current_session(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserSession:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    session = db.scalar(select(UserSession).where(UserSession.token_hash == session_token_hash(token)))
    if not session or _aware(session.expires_at) <= utcnow():
        if session:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")
    session.last_seen_at = utcnow()
    db.commit()
    return session


def get_current_user(session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)) -> User:
    user = db.get(User, session.user_id)
    if not user or user.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User unavailable.")
    return user


def require_csrf(request: Request, session: UserSession = Depends(get_current_session)) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    supplied = request.headers.get("x-csrf-token")
    if not supplied or not secrets.compare_digest(supplied, session.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")


def user_roles(db: Session, user_id: str) -> set[str]:
    return set(db.scalars(select(UserRole.role).where(UserRole.user_id == user_id)).all())


def require_roles(*allowed: str):
    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        roles = user_roles(db, user.id)
        if "ADMIN" not in roles and not roles.intersection(allowed):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role.")
        return user

    return dependency


def enforce_password_changed(request: Request, user: User = Depends(get_current_user)) -> User:
    allowed = {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout"}
    if user.force_password_change and request.url.path not in allowed:
        raise HTTPException(status_code=status.HTTP_428_PRECONDITION_REQUIRED, detail="Password change required.")
    return user


def logout_session(db: Session, session: UserSession) -> None:
    db.execute(delete(UserSession).where(UserSession.id == session.id))
    db.commit()
