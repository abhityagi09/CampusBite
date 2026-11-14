from fastapi import APIRouter

from app.dependencies import CurrentUser, CustomerUser, DbSession, OwnerUser
from app.schemas.statistics import CustomerStats, OwnerStats, Statistics
from app.services import statistics_service as svc

router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("/me", response_model=Statistics)
def my_statistics(db: DbSession, user: CurrentUser):
    """Role-aware dashboard numbers (customer, owner or delivery partner)."""
    return svc.statistics_for(db, user)


@router.get("/owner", response_model=OwnerStats)
def owner_statistics(db: DbSession, owner: OwnerUser):
    """Totals and per-restaurant performance, for the signed-in owner's restaurants only."""
    return svc.owner_stats(db, owner)


@router.get("/customer", response_model=CustomerStats)
def customer_statistics(db: DbSession, customer: CustomerUser):
    """The signed-in customer's own orders and spending only."""
    return svc.customer_stats(db, customer)
