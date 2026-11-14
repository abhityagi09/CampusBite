"""Reminder processing: finds orders that need a reminder, sends it through a notifier and
records it in reminder_logs.

Idempotency: every reminder has an ``event_key`` that is UNIQUE in the database (see
ReminderLog). Per reminder, in one transaction: insert the log row (claims the key) ->
send -> commit.
* the insert hits the unique constraint -> another run already sent it -> skip;
* the send fails -> roll back: no log row, the next run retries it.
A crash between a successful send and the commit can repeat that one notification
(at-least-once), but never creates duplicate log rows.

Owner ORDER_STALE reminders: an order in PLACED or ACCEPTED whose ``status_updated_at`` is
more than 15 minutes old. The key includes the status period, so the same period is reminded
once, and a new eligible period (e.g. placed -> accepted, then idle again) is reminded again.

Runs every minute in the dedicated worker (``python -m app.worker``); ad hoc:
``python -m app.services.reminder_service``.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import ensure_role
from app.models import Order, OrderStatus, ReminderLog, ReminderType, Restaurant, Review, User, UserRole
from app.models.mixins import utcnow
from app.services.notifications import Notification, NotificationError, Notifier

PAYMENT_PENDING_AFTER = timedelta(minutes=15)
REVIEW_REQUEST_AFTER = timedelta(hours=1)
STALE_STATUSES = (OrderStatus.PLACED, OrderStatus.ACCEPTED)

MESSAGES = {
    ReminderType.PAYMENT_PENDING: "Your CampusBite order is waiting for payment.",
    ReminderType.ORDER_READY: "Your CampusBite order is ready.",
    ReminderType.REVIEW_REQUEST: "How was your order? Leave a review.",
    ReminderType.ORDER_STALE: "An order has been waiting more than 15 minutes for your action.",
}


def stale_after() -> timedelta:
    return timedelta(minutes=settings.ORDER_REMINDER_THRESHOLD_MINUTES)


@dataclass(frozen=True)
class DueReminder:
    order_id: UUID
    customer_id: UUID  # recipient (the restaurant owner for ORDER_STALE)
    kind: ReminderType
    restaurant_id: UUID | None = None
    status: OrderStatus | None = None
    status_updated_at: datetime | None = None

    @property
    def event_key(self) -> str:
        if self.kind == ReminderType.ORDER_STALE:
            period = self.status_updated_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
            return f"{self.order_id}:{self.kind.value}:{self.status.value}:{period}"
        return f"{self.order_id}:{self.kind.value}"


@dataclass
class ReminderRunResult:
    sent: int = 0
    skipped_duplicates: int = 0
    failed: int = 0


def _not_logged(kind: ReminderType):
    cond = [ReminderLog.order_id == Order.id, ReminderLog.reminder_type == kind]
    if kind == ReminderType.ORDER_STALE:  # only THIS status period counts
        cond.append(ReminderLog.status_updated_at_snapshot == Order.status_updated_at)
    return ~exists().where(*cond)


def due_reminders(db: Session, now: datetime, limit: int = 500) -> list[DueReminder]:
    customer, owner = Order.customer_id, Restaurant.owner_id
    rules = [
        (ReminderType.PAYMENT_PENDING, customer, [
            Order.status == OrderStatus.PENDING_PAYMENT,
            Order.status_updated_at <= now - PAYMENT_PENDING_AFTER,
        ]),
        (ReminderType.ORDER_READY, customer, [Order.status == OrderStatus.READY]),
        (ReminderType.REVIEW_REQUEST, customer, [
            Order.status == OrderStatus.DELIVERED,
            Order.status_updated_at <= now - REVIEW_REQUEST_AFTER,
            ~exists().where(Review.order_id == Order.id),
        ]),
        (ReminderType.ORDER_STALE, owner, [
            Order.status.in_(STALE_STATUSES),
            Order.status_updated_at < now - stale_after(),  # MORE than the threshold
        ]),
    ]
    due: list[DueReminder] = []
    for kind, recipient, conditions in rules:
        rows = db.execute(
            select(Order.id, recipient, Order.restaurant_id, Order.status, Order.status_updated_at)
            .join(Restaurant, Restaurant.id == Order.restaurant_id)
            .where(*conditions, _not_logged(kind))
            .order_by(Order.status_updated_at, Order.id)
            .limit(limit)
        ).all()
        due += [DueReminder(o, r, kind, rid, st, sua) for o, r, rid, st, sua in rows]
    return due


def send_reminder(db: Session, notifier: Notifier, reminder: DueReminder) -> str:
    """Returns 'sent', 'duplicate' or 'failed'. Leaves the session clean either way."""
    db.add(ReminderLog(
        order_id=reminder.order_id,
        restaurant_id=reminder.restaurant_id,
        reminder_type=reminder.kind,
        event_key=reminder.event_key,
        status_snapshot=reminder.status.value if reminder.status else None,
        status_updated_at_snapshot=reminder.status_updated_at,
    ))
    try:
        db.flush()  # claims the event key (UNIQUE)
    except IntegrityError:
        db.rollback()
        return "duplicate"
    try:
        notifier.send(Notification(user_id=reminder.customer_id, order_id=reminder.order_id,
                                   kind=reminder.kind, message=MESSAGES[reminder.kind]))
    except NotificationError:
        db.rollback()  # no log row: retried on the next run
        return "failed"
    db.commit()
    return "sent"


def process_reminders(db: Session, notifier: Notifier, now: datetime | None = None) -> ReminderRunResult:
    result = ReminderRunResult()
    for reminder in due_reminders(db, now or utcnow()):
        outcome = send_reminder(db, notifier, reminder)
        if outcome == "sent":
            result.sent += 1
        elif outcome == "duplicate":
            result.skipped_duplicates += 1
        else:
            result.failed += 1
    return result


# ---- owner API -------------------------------------------------------------------------
def _owner_scope(owner: User):
    return (
        select(ReminderLog, Order, Restaurant.name)
        .join(Order, Order.id == ReminderLog.order_id)
        .join(Restaurant, Restaurant.id == ReminderLog.restaurant_id)
        .where(Restaurant.owner_id == owner.id, ReminderLog.reminder_type == ReminderType.ORDER_STALE)
    )


def _to_read(log: ReminderLog, order: Order, name: str):
    from app.schemas.reminder import OwnerReminderRead

    still = order.status.value == log.status_snapshot and order.status_updated_at == log.status_updated_at_snapshot
    return OwnerReminderRead(
        id=log.id, order_id=order.id, restaurant_id=log.restaurant_id, restaurant_name=name,
        reminder_type=log.reminder_type, status_snapshot=log.status_snapshot,
        status_updated_at_snapshot=log.status_updated_at_snapshot, created_at=log.sent_at,
        read_at=log.read_at, is_read=log.read_at is not None,
        overdue_minutes_at_reminder=int((log.sent_at - log.status_updated_at_snapshot).total_seconds() // 60)
        if log.status_updated_at_snapshot else None,
        current_order_status=order.status, still_waiting=still,
    )


def list_owner_reminders(db: Session, owner: User, page, unread_only: bool = False):
    from app.schemas.common import Page

    ensure_role(owner, UserRole.OWNER)
    stmt = _owner_scope(owner).order_by(ReminderLog.sent_at.desc(), ReminderLog.id.desc())
    if unread_only:
        stmt = stmt.where(ReminderLog.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(items=[_to_read(*r) for r in rows], total=total, limit=page.limit, offset=page.offset)


def unread_count(db: Session, owner: User) -> int:
    ensure_role(owner, UserRole.OWNER)
    stmt = _owner_scope(owner).where(ReminderLog.read_at.is_(None))
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def mark_read(db: Session, owner: User, reminder_id: UUID):
    ensure_role(owner, UserRole.OWNER)
    row = db.execute(_owner_scope(owner).where(ReminderLog.id == reminder_id)).first()
    if row is None:  # missing OR another owner's: indistinguishable on purpose
        raise NotFoundError("Reminder not found")
    log = row[0]
    if log.read_at is None:  # idempotent
        log.read_at = utcnow()
        db.commit()
    return _to_read(*row)


if __name__ == "__main__":  # pragma: no cover
    from app.worker import run_once

    print(run_once())
