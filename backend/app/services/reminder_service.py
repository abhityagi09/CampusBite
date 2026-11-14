"""Reminder processing: finds orders that need a reminder, sends it through a notifier and
records it in reminder_logs.

Event key = (order_id, reminder_type), enforced by the UNIQUE constraint on reminder_logs,
so each reminder is sent at most once per order, even with several workers running.

Per reminder, in one transaction: insert the log row (claims the event key), send, commit.
* insert hits the unique constraint -> someone else already sent it -> skip;
* the send fails -> roll back, so no log is left and the next run retries it.
(A crash between a successful send and the commit can still repeat one reminder: the
usual at-least-once trade-off for a notifier without its own idempotency.)

Run periodically, e.g. from cron:  python -m app.services.reminder_service
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Order, OrderStatus, ReminderLog, ReminderType, Review
from app.models.mixins import utcnow
from app.services.notifications import Notification, NotificationError, Notifier

PAYMENT_PENDING_AFTER = timedelta(minutes=15)
REVIEW_REQUEST_AFTER = timedelta(hours=1)

MESSAGES = {
    ReminderType.PAYMENT_PENDING: "Your CampusBite order is waiting for payment.",
    ReminderType.ORDER_READY: "Your CampusBite order is ready.",
    ReminderType.REVIEW_REQUEST: "How was your order? Leave a review.",
}


@dataclass(frozen=True)
class DueReminder:
    order_id: UUID
    customer_id: UUID
    kind: ReminderType


@dataclass
class ReminderRunResult:
    sent: int = 0
    skipped_duplicates: int = 0
    failed: int = 0


def _not_logged(kind: ReminderType):
    return ~exists().where(ReminderLog.order_id == Order.id, ReminderLog.reminder_type == kind)


def due_reminders(db: Session, now: datetime, limit: int = 500) -> list[DueReminder]:
    rules = [
        (ReminderType.PAYMENT_PENDING, [
            Order.status == OrderStatus.PENDING_PAYMENT,
            Order.created_at <= now - PAYMENT_PENDING_AFTER,
        ]),
        (ReminderType.ORDER_READY, [Order.status == OrderStatus.READY_FOR_PICKUP]),
        (ReminderType.REVIEW_REQUEST, [
            Order.status == OrderStatus.DELIVERED,
            Order.updated_at <= now - REVIEW_REQUEST_AFTER,
            ~exists().where(Review.order_id == Order.id),
        ]),
    ]
    due: list[DueReminder] = []
    for kind, conditions in rules:
        rows = db.execute(
            select(Order.id, Order.customer_id)
            .where(*conditions, _not_logged(kind))
            .order_by(Order.created_at, Order.id)
            .limit(limit)
        ).all()
        due += [DueReminder(order_id=o, customer_id=c, kind=kind) for o, c in rows]
    return due


def send_reminder(db: Session, notifier: Notifier, reminder: DueReminder) -> str:
    """Returns 'sent', 'duplicate' or 'failed'."""
    db.add(ReminderLog(order_id=reminder.order_id, reminder_type=reminder.kind))
    try:
        db.flush()  # claims the (order, type) event key
    except IntegrityError:
        db.rollback()
        return "duplicate"
    try:
        notifier.send(
            Notification(
                user_id=reminder.customer_id,
                order_id=reminder.order_id,
                kind=reminder.kind,
                message=MESSAGES[reminder.kind],
            )
        )
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


if __name__ == "__main__":  # pragma: no cover
    from app.database.session import SessionLocal
    from app.services.notifications import MockNotifier

    with SessionLocal() as session:
        print(process_reminders(session, MockNotifier()))
