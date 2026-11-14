import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"
_RESERVED_CLAIMS = {"sub", "exp", "iat", "nbf", "iss", "jti", "type"}


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except ValueError:
        return False


@lru_cache
def _dummy_hash() -> str:
    return hash_password("not-a-real-password-0")


def burn_password_check(password: str) -> None:
    """Spend the same time as a real bcrypt check.

    Called when the e-mail is unknown, so response time does not reveal which e-mails have
    accounts."""
    verify_password(password, _dummy_hash())


def create_access_token(
    subject: str | uuid.UUID,
    extra_claims: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
    now: datetime | None = None,
) -> str:
    """Signed JWT with sub, type=access, iss, iat, exp and a unique jti.

    ``extra_claims`` can add informational claims but can never override the reserved ones.
    ``expires_minutes`` may be negative (tests use it to mint an already-expired token)."""
    issued = now or datetime.now(timezone.utc)
    minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES if expires_minutes is None else expires_minutes
    payload: dict[str, Any] = {
        **{k: v for k, v in (extra_claims or {}).items() if k not in _RESERVED_CLAIMS},
        "sub": str(subject),
        "type": ACCESS_TOKEN_TYPE,
        "iss": settings.JWT_ISSUER,
        "iat": issued,
        "exp": issued + timedelta(minutes=minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature, expiry, issuer, subject and token type.

    Only the configured algorithm is accepted (so "alg: none" and algorithm-confusion tokens
    fail). Raises jwt.PyJWTError (ExpiredSignatureError for expiry) on any problem."""
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        options={"require": ["exp", "iat", "sub", "iss"]},
        leeway=5,  # seconds of clock skew tolerated
    )
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Wrong token type")
    if not isinstance(payload["sub"], str) or not payload["sub"]:
        raise jwt.InvalidSubjectError("Invalid subject")
    return payload
