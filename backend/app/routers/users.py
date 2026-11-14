from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from uuid import UUID

from app.dependencies import DbSession, OwnerUser
from app.models import User, UserRole

router = APIRouter(prefix="/users", tags=["users"])


class DeliveryPartnerRead(BaseModel):
    """Only what an owner needs to pick a courier: no e-mail or phone."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


@router.get("/delivery-partners", response_model=list[DeliveryPartnerRead])
def list_delivery_partners(db: DbSession, owner: OwnerUser):
    """Active delivery partners, for POST /orders/{id}/assign-delivery (owners only)."""
    return db.scalars(
        select(User)
        .where(User.role == UserRole.DELIVERY_PARTNER, User.is_active.is_(True))
        .order_by(User.name, User.id)
    ).all()
