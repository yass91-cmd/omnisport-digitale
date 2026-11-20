"""Password hashing, opaque sessions, same-origin writes and shared login limits."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Header, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .database import get_session
from .models import AuthAttemptBucket, LoginSession, User

Database = Annotated[Session, Depends(get_session)]
# OWASP Argon2id baseline; explicit parameters keep container memory bounded.
passwords = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
dummy_hash = passwords.hash(secrets.token_urlsafe(32))


def utcnow() -> datetime:
    """All persisted auth timestamps are naive UTC, independent of server timezone."""
    return datetime.now(UTC).replace(tzinfo=None)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_token(value: str) -> str:
    return hmac.new(value.encode(), b"omnisport-csrf-v1", hashlib.sha256).hexdigest()


def password_matches(encoded: str, password: str) -> bool:
    try:
        return passwords.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def same_origin_write(
    request: Request,
    omni_request: Annotated[str | None, Header(alias="X-Omni-Request")] = None,
):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if (
        omni_request != "1"
        or (origin is not None and origin not in request.app.state.settings.auth_origins)
        or request.headers.get("sec-fetch-site") == "cross-site"
        or request.headers.get("content-type", "").split(";")[0].strip() != "application/json"
    ):
        raise HTTPException(403, "This request is not allowed. Reload the page and try again.")


def consume_attempts(session: Session, request: Request, email: str, *, register=False):
    """Atomic fixed-window counters shared by application processes through MySQL."""
    settings = request.app.state.settings
    now = utcnow()
    window = int(now.replace(tzinfo=UTC).timestamp()) // 600
    expiry = datetime.fromtimestamp((window + 1) * 600, UTC).replace(tzinfo=None)
    ip = request.client.host if request.client else "unknown"
    limits = (
        [(f"register:ip:{ip}", 20)]
        if register
        else [
            (f"login:ip:{ip}", settings.login_ip_limit),
            (f"login:email:{email}", settings.login_email_limit),
        ]
    )
    session.execute(delete(AuthAttemptBucket).where(AuthAttemptBucket.expires_at < now))
    exceeded = False
    for scope, maximum in limits:
        key = token_hash(f"{window}:{scope}")
        values = {"key": key, "attempts": 1, "expires_at": expiry}
        if session.get_bind().dialect.name == "mysql":
            statement = mysql_insert(AuthAttemptBucket).values(**values)
            statement = statement.on_duplicate_key_update(attempts=AuthAttemptBucket.attempts + 1)
        else:
            statement = sqlite_insert(AuthAttemptBucket).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=[AuthAttemptBucket.key],
                set_={"attempts": AuthAttemptBucket.attempts + 1},
            )
        session.execute(statement)
        count = session.scalar(
            select(AuthAttemptBucket.attempts).where(AuthAttemptBucket.key == key)
        )
        exceeded |= count > maximum
    session.commit()
    if exceeded:
        raise HTTPException(
            429,
            "Too many attempts. Please try again later.",
            headers={"Retry-After": str(max(1, int((expiry - now).total_seconds())))},
        )


@dataclass
class Identity:
    user: User
    session: LoginSession
    token: str


def current_identity(request: Request, session: Database) -> Identity:
    token = request.cookies.get(request.app.state.settings.session_cookie, "")
    if len(token) != 43:
        raise HTTPException(401, "Please sign in to continue.")
    login = session.get(LoginSession, token_hash(token))
    now = utcnow()
    if (
        login is None
        or login.expires_at <= now
        or login.last_seen_at
        <= now - timedelta(minutes=request.app.state.settings.session_idle_minutes)
        or not login.user.active
    ):
        if login is not None:
            session.delete(login)
            session.commit()
        raise HTTPException(401, "Please sign in to continue.")
    login.last_seen_at = now
    session.commit()
    return Identity(login.user, login, token)


CurrentIdentity = Annotated[Identity, Depends(current_identity)]


def require_csrf(
    identity: CurrentIdentity,
    supplied: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Identity:
    if (
        not supplied
        or not supplied.isascii()
        or not hmac.compare_digest(supplied, csrf_token(identity.token))
    ):
        raise HTTPException(403, "Reload your account page and try again.")
    return identity


CsrfIdentity = Annotated[Identity, Depends(require_csrf)]


def create_session(session: Session, request: Request, response: Response, user: User) -> str:
    settings = request.app.state.settings
    now = utcnow()
    old_token = request.cookies.get(settings.session_cookie, "")
    if old_token:
        session.execute(
            delete(LoginSession).where(LoginSession.token_hash == token_hash(old_token))
        )
    session.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    session.add(
        LoginSession(
            token_hash=token_hash(token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_hours),
        )
    )
    session.commit()
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return csrf_token(token)
