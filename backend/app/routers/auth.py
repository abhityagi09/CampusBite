from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from fastapi.security import OAuth2PasswordRequestForm

from app.core.security import create_access_token
from app.dependencies import CurrentUser, DbSession
from app.models import User
from app.schemas.user import (
    LoginRequest,
    PasswordChange,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> TokenResponse:
    # "role" in the token is informational for the frontend; the server never trusts it.
    token = create_access_token(user.id, {"role": user.role.value})
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@router.post("/register", response_model=UserRead, status_code=201)
def register(
    data: UserCreate,
    db: DbSession,
    x_registration_key: Annotated[
        str | None,
        Header(
            description="Required only for role 'owner' or 'delivery_partner'. "
            "Public sign-up can only create customers.",
        ),
    ] = None,
):
    """Create an account. Anyone may register as `customer`; `owner` and `delivery_partner`
    need the staff key in the `X-Registration-Key` header (403 otherwise)."""
    return auth_service.register_user(db, data, x_registration_key)


@router.post("/login", response_model=TokenResponse)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession):
    """OAuth2 password-flow login (form fields: username = your e-mail, password).
    This is the endpoint behind the Authorize button in Swagger UI (/docs)."""
    user = auth_service.authenticate(db, form.username, form.password)
    return _token_response(user)


@router.post("/login/json", response_model=TokenResponse)
def login_json(data: LoginRequest, db: DbSession):
    """JSON login for the React frontend."""
    user = auth_service.authenticate(db, data.email, data.password)
    return _token_response(user)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser):
    """The authenticated user (never includes the password hash)."""
    return user


@router.patch("/me", response_model=UserRead)
def update_me(data: UserUpdate, db: DbSession, user: CurrentUser):
    return auth_service.update_profile(db, user, data)


@router.post("/change-password", status_code=204)
def change_password(data: PasswordChange, db: DbSession, user: CurrentUser):
    auth_service.change_password(db, user, data)
    return Response(status_code=204)
