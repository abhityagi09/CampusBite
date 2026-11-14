from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies import DbSession, OwnerUser
from app.dependencies.query import PageParams
from app.schemas.common import Page
from app.schemas.reminder import OwnerReminderRead, UnreadCount
from app.services import reminder_service as svc

router = APIRouter(prefix="/owner/reminders", tags=["owner reminders"])


@router.get("", response_model=Page[OwnerReminderRead])
def list_reminders(db: DbSession, owner: OwnerUser, page: PageParams,
                   unread_only: bool = Query(False, description="Only unread reminders")):
    """Idle-order reminders (placed / accepted for 15+ minutes) for YOUR restaurants, newest first."""
    return svc.list_owner_reminders(db, owner, page, unread_only)


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(db: DbSession, owner: OwnerUser):
    return {"unread": svc.unread_count(db, owner)}


@router.patch("/{reminder_id}/read", response_model=OwnerReminderRead)
def mark_read(reminder_id: UUID, db: DbSession, owner: OwnerUser):
    """Idempotent. Another owner's reminder answers 404."""
    return svc.mark_read(db, owner, reminder_id)
