import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Restaurant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "restaurants"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    cuisine: Mapped[str | None] = mapped_column(String(60), index=True)
    location: Mapped[str | None] = mapped_column(String(200))
    # is_active: listed on the platform at all (suspension / soft delete).
    # is_open:   currently accepting orders (the owner flips this during the day).
    is_active: Mapped[bool] = mapped_column(default=True)
    is_open: Mapped[bool] = mapped_column(default=True)

    owner: Mapped["User"] = relationship(back_populates="restaurants")
    menu_items: Mapped[list["MenuItem"]] = relationship(
        back_populates="restaurant",
        cascade="all, delete-orphan",
        order_by="MenuItem.created_at, MenuItem.id",
    )
    orders: Mapped[list["Order"]] = relationship(back_populates="restaurant")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="restaurant", overlaps="order"
    )


class MenuItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "menu_items"
    __table_args__ = (CheckConstraint("price > 0", name="price_positive"),)

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(60))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    is_available: Mapped[bool] = mapped_column(default=True)

    restaurant: Mapped[Restaurant] = relationship(back_populates="menu_items")
