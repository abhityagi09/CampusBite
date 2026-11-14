from fastapi import APIRouter, Query

from app.dependencies import DbSession, DeliveryUser
from app.dependencies.query import PageParams
from app.models import OrderStatus
from app.schemas.common import Page
from app.schemas.order import OrderRead
from app.services import order_service as svc

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.get("/me", response_model=Page[OrderRead])
def my_deliveries(
    db: DbSession,
    partner: DeliveryUser,
    page: PageParams,
    status_filter: OrderStatus | None = Query(None, alias="status"),
):
    """Orders assigned to the signed-in delivery partner, newest first."""
    return svc.list_my_deliveries(db, partner, status_filter, page)
