"""Notification adapter boundary. Only a mock exists for now; a real e-mail/push adapter
would implement the same ``send`` method."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.models import ReminderType


class NotificationError(Exception):
    """The channel failed; the caller must treat the notification as NOT sent."""


@dataclass(frozen=True)
class Notification:
    user_id: UUID
    order_id: UUID
    kind: ReminderType
    message: str


class Notifier(Protocol):
    def send(self, notification: Notification) -> None: ...


@dataclass
class MockNotifier:
    """Records notifications in memory. ``fail_for`` makes sends for those orders fail."""

    sent: list[Notification] = field(default_factory=list)
    fail_for: set[UUID] = field(default_factory=set)

    def send(self, notification: Notification) -> None:
        if notification.order_id in self.fail_for:
            raise NotificationError(f"mock channel failure for order {notification.order_id}")
        self.sent.append(notification)
