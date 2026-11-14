from datetime import datetime
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

from app.models.enums import UserRole


def _check_password(value: str) -> str:
    # bcrypt only uses the first 72 bytes
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
        raise ValueError("Password must contain at least one letter and one digit")
    if not value.strip():
        raise ValueError("Password cannot be blank")
    return value


# Requests accept the old field name "full_name" as an alias of "name" so existing
# clients keep working. Responses only ever contain "name".
_NAME_ALIASES = AliasChoices("name", "full_name")


class UserCreate(BaseModel):
    # extra="forbid": unknown fields (is_active, is_admin, ...) are an error, never ignored.
    model_config = ConfigDict(
        str_strip_whitespace=True, populate_by_name=True, extra="forbid"
    )

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=120, validation_alias=_NAME_ALIASES)
    phone: str | None = Field(default=None, max_length=20)
    role: UserRole

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def _password_ok(cls, v: str) -> str:
        return _check_password(v)


class UserUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    name: str | None = Field(
        default=None, min_length=1, max_length=120, validation_alias=_NAME_ALIASES
    )
    phone: str | None = Field(default=None, max_length=20)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def _password_ok(cls, v: str) -> str:
        return _check_password(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    phone: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
