from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies import CustomerUser, DbSession, OwnerUser
from app.dependencies.query import PageParams
from app.models import RefundStatus
from app.schemas.common import Page
from app.schemas.refund import RefundDecision, RefundRequestBody, RefundRequestRead
from app.services import refund_service as svc

router = APIRouter(tags=["refunds"])


@router.post("/orders/{order_id}/refund-requests", response_model=RefundRequestRead, status_code=201)
def request_refund(order_id: UUID, data: RefundRequestBody, db: DbSession, customer: CustomerUser):
    """Customer asks for a refund of a delivered, paid order (one open request per order)."""
    return svc.request_refund(db, customer, order_id, data.reason)


@router.get("/refund-requests/me", response_model=Page[RefundRequestRead])
def my_refund_requests(db: DbSession, customer: CustomerUser, page: PageParams):
    return svc.list_my_refund_requests(db, customer, page)


@router.get("/refund-requests/incoming", response_model=Page[RefundRequestRead])
def incoming_refund_requests(
    db: DbSession,
    owner: OwnerUser,
    page: PageParams,
    status_filter: RefundStatus | None = Query(None, alias="status"),
):
    """Refund requests for orders at the signed-in owner's restaurants."""
    return svc.list_incoming_refund_requests(db, owner, status_filter, page)


@router.post("/refund-requests/{request_id}/decision", response_model=RefundRequestRead)
def decide_refund(request_id: UUID, data: RefundDecision, db: DbSession, owner: OwnerUser):
    """approve: payment refunded + reversal ledger entry, atomically (status 'processed').
    reject: status 'rejected'. Each request can be decided once."""
    return svc.decide_refund(db, owner, request_id, data.decision)
