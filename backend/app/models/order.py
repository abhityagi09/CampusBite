import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import (
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    enum_column,
)
from app.models.mixins import UTCDateTime, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.restaurant import Restaurant
from app.models.user import User


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="total_non_negative"),
        # Targets for composite foreign keys: they let reviews / refund requests prove
        # that their customer (and restaurant) really are the order's customer/restaurant.
        UniqueConstraint("id", "customer_id", name="uq_orders_id_customer_id"),
        UniqueConstraint(
            "id", "customer_id", "restaurant_id", name="uq_orders_id_customer_id_restaurant_id"
        ),
        Index("ix_orders_restaurant_id_status", "restaurant_id", "status"),
        Index("ix_orders_customer_id_created_at", "customer_id", "created_at"),
        # Checkout idempotency: one order per (customer, Idempotency-Key). NULL keys
        # (orders placed without a key) are not constrained.
        UniqueConstraint(
            "customer_id", "idempotency_key", name="uq_orders_customer_id_idempotency_key"
        ),
        Index("ix_orders_status_status_updated_at", "status", "status_updated_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id"))
    delivery_partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus, 30, "order_status"),
        index=True,
        default=OrderStatus.PENDING_PAYMENT,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    delivery_address: Mapped[str] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(String(500))
    # Client-chosen Idempotency-Key header and a SHA-256 of the request body it was first
    # used with, so a retry with the same key but a different cart is detected.
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    # When the order entered its CURRENT status (set on creation and on every status change,
    # untouched by other updates). Drives "idle for 15 minutes" reminders.
    status_updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, server_default=func.now()
    )

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.id",
    )
    events: Mapped[list["OrderStatusEvent"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderStatusEvent.created_at, OrderStatusEvent.id",
    )
    payment: Mapped["Payment | None"] = relationship(
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )
    # The ledger is append-only financial history: no delete cascade.
    ledger_entries: Mapped[list["PaymentLedger"]] = relationship(
        back_populates="order", order_by="PaymentLedger.created_at, PaymentLedger.id"
    )
    review: Mapped["Review | None"] = relationship(
        back_populates="order", uselist=False, overlaps="customer,restaurant,reviews"
    )
    refund_requests: Mapped[list["RefundRequest"]] = relationship(
        back_populates="order", overlaps="customer,refund_requests"
    )
    reminder_logs: Mapped[list["ReminderLog"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    restaurant: Mapped[Restaurant] = relationship(back_populates="orders")
    customer: Mapped[User] = relationship(
        back_populates="orders", foreign_keys=[customer_id]
    )
    delivery_partner: Mapped[User | None] = relationship(
        back_populates="deliveries", foreign_keys=[delivery_partner_id]
    )


class OrderItem(UUIDPrimaryKeyMixin, Base):
    """Snapshot of a menu item at order time (name and price never change later)."""

    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        UniqueConstraint("order_id", "menu_item_id", name="uq_order_items_order_id_menu_item_id"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    # Nullable + SET NULL: owners may delete a menu item that past orders still reference.
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("menu_items.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Generated by the database, so it can never disagree with quantity * unit_price.
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), Computed("quantity * unit_price", persisted=True)
    )

    order: Mapped[Order] = relationship(back_populates="items")


class OrderStatusEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only history used for delivery tracking."""

    __tablename__ = "order_status_events"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[OrderStatus] = mapped_column(enum_column(OrderStatus, 30, "order_status"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, server_default=func.now()
    )

    order: Mapped[Order] = relationship(back_populates="events")


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current payment state of an order (one row per order). History is in payment_ledger."""

    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount >= 0", name="amount_non_negative"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    method: Mapped[PaymentMethod] = mapped_column(
        enum_column(PaymentMethod, 20, "payment_method")
    )
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus, 20, "payment_status"), default=PaymentStatus.PENDING
    )
    transaction_ref: Mapped[str | None] = mapped_column(String(40), unique=True)
    failure_reason: Mapped[str | None] = mapped_column(String(200))

    order: Mapped[Order] = relationship(back_populates="payment")
