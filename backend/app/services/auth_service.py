import hmac

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)
from app.core.config import settings
from app.core.permissions import PRIVILEGED_ROLES
from app.core.security import burn_password_check, hash_password, verify_password
from app.models import User, UserRole
from app.schemas.user import PasswordChange, UserCreate, UserUpdate


def _authorize_role(role: UserRole, registration_key: str | None) -> None:
    """Public sign-up may only create customers; other roles need the staff key."""
    if role not in PRIVILEGED_ROLES:
        return
    expected = settings.STAFF_REGISTRATION_KEY
    if expected is None:
        raise ForbiddenError(f"Registering as '{role.value}' is disabled")
    if registration_key is None or not hmac.compare_digest(
        registration_key.encode("utf-8"), expected.get_secret_value().encode("utf-8")
    ):
        raise ForbiddenError(f"Registering as '{role.value}' requires authorization")


def register_user(
    db: Session, data: UserCreate, registration_key: str | None = None
) -> User:
    _authorize_role(data.role, registration_key)
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ConflictError("An account with this email already exists")

    user = User(
        email=email,
        name=data.name,
        phone=data.phone,
        role=data.role,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("An account with this email already exists") from None
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    # Same error for unknown email and wrong password, so accounts can't be probed.
    if user is None:
        burn_password_check(password)  # keep timing the same as a wrong password
        raise UnauthorizedError("Incorrect email or password")
    if not verify_password(password, user.password_hash):
        raise UnauthorizedError("Incorrect email or password")
    if not user.is_active:
        raise UnauthorizedError("This account is disabled")
    return user


def update_profile(db: Session, user: User, data: UserUpdate) -> User:
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, data: PasswordChange) -> None:
    if not verify_password(data.current_password, user.password_hash):
        raise BadRequestError("Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    db.commit()
