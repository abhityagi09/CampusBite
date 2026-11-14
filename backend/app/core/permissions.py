"""Authorization helpers used by the SERVICE layer.

Route dependencies (CustomerUser, OwnerUser...) are the first line of defence. These helpers
are the second: services re-check the caller's role and ownership themselves, so a service
called from a new route, a background job or a test can never skip authorization.
"""

from app.core.exceptions import ForbiddenError
from app.models import User, UserRole


def ensure_role(user: User, *roles: UserRole) -> None:
    if user.role not in roles:
        raise ForbiddenError("Your account role cannot perform this action")


PRIVILEGED_ROLES = frozenset({UserRole.OWNER, UserRole.DELIVERY_PARTNER})
