from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _PartialUpdate(BaseModel):
    """PATCH body: omitted fields are left alone, but an explicit ``null`` is only allowed
    for columns that are nullable (it clears them). ``null`` for a required column is a 422
    rather than being silently ignored."""

    model_config = ConfigDict(str_strip_whitespace=True)
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_null_for_required_fields(self):
        nulled = sorted(
            f for f in self.model_fields_set & self.NOT_NULLABLE if getattr(self, f) is None
        )
        if nulled:
            raise ValueError(f"These fields cannot be null: {', '.join(nulled)}")
        return self


# ---- menu items --------------------------------------------------------------


class MenuItemCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=60)
    # Numeric(10, 2) in the database: positive, at most 99,999,999.99.
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    is_available: bool = True


class MenuItemUpdate(_PartialUpdate):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"name", "price", "is_available"})

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=60)
    price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    is_available: bool | None = None


class MenuItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    name: str
    description: str | None
    category: str | None
    price: Decimal
    is_available: bool
    created_at: datetime
    updated_at: datetime


class MenuItemSearchResult(MenuItemRead):
    """A menu item found by the cross-restaurant search, with enough restaurant context
    to display it without a second request."""

    restaurant_name: str
    restaurant_is_open: bool


# ---- restaurants -------------------------------------------------------------


class RestaurantCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    cuisine: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=200)
    is_open: bool = True


class RestaurantUpdate(_PartialUpdate):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"name", "is_open", "is_active"})

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    cuisine: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=200)
    is_open: bool | None = None
    is_active: bool | None = None


class RestaurantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    cuisine: str | None
    location: str | None
    is_active: bool
    is_open: bool
    created_at: datetime
    updated_at: datetime
    average_rating: float | None = None
    review_count: int = 0


class RestaurantDetail(RestaurantRead):
    menu_items: list[MenuItemRead] = []
