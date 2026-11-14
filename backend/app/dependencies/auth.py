from typing import Annotated

from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.dependencies.db import DbSession
from app.models import User, UserRole

# tokenUrl is what Swagger's "Authorize" dialog posts the username/password form to.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbSession
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Token has expired") from None
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        # bad signature, wrong type/issuer, missing claims, malformed subject ...
        raise UnauthorizedError() from None

    user = db.get(User, user_id)
    # The role is always read from the database, never from the token, so demoting or
    # disabling a user takes effect immediately even for tokens already issued.
    if user is None or not user.is_active:
        raise UnauthorizedError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """Dependency factory: ``Depends(require_roles(UserRole.OWNER, ...))``.

    401 comes from get_current_user (no/invalid token); this adds 403 for a valid user whose
    role is not allowed."""

    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise ForbiddenError("Your account role cannot perform this action")
        return user

    return checker


CustomerUser = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]
OwnerUser = Annotated[User, Depends(require_roles(UserRole.OWNER))]
DeliveryUser = Annotated[User, Depends(require_roles(UserRole.DELIVERY_PARTNER))]
