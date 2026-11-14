import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.mixins import UTCDateTime, UUIDPrimaryKeyMixin, utcnow


class Review(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),
        # The review's customer and restaurant must be the order's own customer and
        # restaurant: the database rejects a review that points at a mismatched order.
        ForeignKeyConstraint(
            ["order_id", "customer_id", "restaurant_id"],
            ["orders.id", "orders.customer_id", "orders.restaurant_id"],
            name="fk_reviews_order_id_customer_id_restaurant_id_orders",
        ),
    )

    # unique=True: at most ONE review per order, enforced by the database.
    order_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    rating: Mapped[int]
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, server_default=func.now()
    )

    order: Mapped["Order"] = relationship(
        back_populates="review", overlaps="customer,restaurant"
    )
    customer: Mapped["User"] = relationship(back_populates="reviews", overlaps="order")
    restaurant: Mapped["Restaurant"] = relationship(
        back_populates="reviews", overlaps="order"
    )
