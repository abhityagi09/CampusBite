from uuid import UUID
from fastapi import APIRouter

from app.dependencies import CurrentUser, CustomerUser, DbSession
from app.schemas.payment import PaymentCreate, PaymentLedgerRead, PaymentRead
from app.services import payment_service as svc

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/orders/{order_id}/pay", response_model=PaymentRead)
def pay_order(order_id: UUID, data: PaymentCreate, db: DbSession, customer: CustomerUser):
    """Simulated payment. On success the order moves to 'placed'.
    On failure the response has status 'failed' and the order stays pending_payment."""
    return svc.pay_order(db, customer, order_id, data)


@router.get("/orders/{order_id}", response_model=PaymentRead)
def get_payment(order_id: UUID, db: DbSession, user: CurrentUser):
    return svc.get_payment(db, user, order_id)


@router.get("/orders/{order_id}/ledger", response_model=list[PaymentLedgerRead])
def get_ledger(order_id: UUID, db: DbSession, user: CurrentUser):
    """Append-only charge/refund history for an order."""
    return svc.get_ledger(db, user, order_id)
