"""Customer refund requests and the restaurant owner's decision on them.

Flow:  requested --owner rejects--> rejected
       requested --owner approves--> processed   (payment refunded + REFUND ledger entry,
                                                  all in one transaction)
Automatic refunds for cancelled / rejected orders are handled by order_service.apply_status;
this module covers paid orders that were DELIVERED (e.g. wrong or missing food).

Duplicate protection, in layers:
* the order row is locked and the request is re-checked inside the transaction;
* a partial unique index allows only one open request per order;
* status writes are compare-and-set (``WHERE status = <expected>``), so two concurrent
  approvals cannot both refund;
* the ledger reference is derived from the request id and is unique.
"""

import hashlib
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import ensure_role
from app.models import (
    LedgerStatus,
    Order,
    OrderStatus,
    Payment,
    PaymentLedger,
    PaymentStatus,
    RefundRequest,
    RefundStatus,
    Restaurant,
    TransactionType,
    User,
    UserRole,
)
from app.models.mixins import utcnow
from app.schemas.common import Page
from app.schemas.refund import RefundRequestRead
from app.services.order_service import load_order
from app.services.restaurant_service import Pagination

REFUNDABLE_ORDER_STATUSES = frozenset({OrderStatus.DELIVERED})
OPEN = (RefundStatus.REQUESTED, RefundStatus.APPROVED)


def _page(db: Session, stmt, page: Pagination) -> Page[RefundRequestRead]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[RefundRequestRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def _cas(db: Session, model, row_id: UUID, expected, new) -> None:
    result = db.execute(
        update(model)
        .where(model.id == row_id, model.status == expected)
        .values(status=new, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise ConflictError("This refund was already handled. Reload and try again.")


def refund_reference(request_id: UUID) -> str:
    return "RFND-" + hashlib.sha256(str(request_id).encode()).hexdigest()[:20].upper()


# ---- customer ----------------------------------------------------------------


def request_refund(db: Session, customer: User, order_id: UUID, reason: str) -> RefundRequest:
    ensure_role(customer, UserRole.CUSTOMER)
    order = load_order(db, order_id, lock=True)
    if order is None or order.customer_id != customer.id:
        raise NotFoundError("Order not found")  # never reveal other customers' orders
    if order.status not in REFUNDABLE_ORDER_STATUSES:
        raise ConflictError(
            f"Refunds can be requested for delivered orders; this one is '{order.status.value}'"
        )
    payment = order.payment
    if payment is None or payment.status != PaymentStatus.PAID:
        state = "already refunded" if payment and payment.status == PaymentStatus.REFUNDED else "not paid"
        raise ConflictError(f"This order is {state}")
    if db.scalar(
        select(RefundRequest.id).where(
            RefundRequest.order_id == order.id, RefundRequest.status.in_(OPEN)
        )
    ):
        raise ConflictError("A refund request for this order is already open")

    req = RefundRequest(order_id=order.id, customer_id=customer.id, reason=reason)
    db.add(req)
    try:
        db.commit()
    except IntegrityError:  # concurrent duplicate hit the partial unique index
        db.rollback()
        raise ConflictError("A refund request for this order is already open") from None
    db.refresh(req)
    return req


def list_my_refund_requests(db: Session, customer: User, page: Pagination) -> Page[RefundRequestRead]:
    ensure_role(customer, UserRole.CUSTOMER)
    stmt = (
        select(RefundRequest)
        .where(RefundRequest.customer_id == customer.id)
        .order_by(RefundRequest.created_at.desc(), RefundRequest.id.desc())
    )
    return _page(db, stmt, page)


# ---- owner -------------------------------------------------------------------


def list_incoming_refund_requests(
    db: Session, owner: User, status: RefundStatus | None, page: Pagination
) -> Page[RefundRequestRead]:
    ensure_role(owner, UserRole.OWNER)
    stmt = (
        select(RefundRequest)
        .join(Order, Order.id == RefundRequest.order_id)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(Restaurant.owner_id == owner.id)
        .order_by(RefundRequest.created_at.desc(), RefundRequest.id.desc())
    )
    if status is not None:
        stmt = stmt.where(RefundRequest.status == status)
    return _page(db, stmt, page)


def decide_refund(
    db: Session, owner: User, request_id: UUID, decision: Literal["approve", "reject"]
) -> RefundRequest:
    ensure_role(owner, UserRole.OWNER)
    req = db.scalar(select(RefundRequest).where(RefundRequest.id == request_id).with_for_update())
    if req is None:
        raise NotFoundError("Refund request not found")
    order = load_order(db, req.order_id, lock=True)
    if order is None or order.restaurant.owner_id != owner.id:
        raise NotFoundError("Refund request not found")
    if req.status != RefundStatus.REQUESTED:
        raise ConflictError(f"This refund request is already '{req.status.value}'")

    try:
        if decision == "reject":
            _cas(db, RefundRequest, req.id, RefundStatus.REQUESTED, RefundStatus.REJECTED)
        else:
            payment = order.payment
            if payment is None or payment.status != PaymentStatus.PAID:
                raise ConflictError("This order's payment is not refundable (already refunded?)")
            _cas(db, RefundRequest, req.id, RefundStatus.REQUESTED, RefundStatus.PROCESSED)
            _cas(db, Payment, payment.id, PaymentStatus.PAID, PaymentStatus.REFUNDED)
            db.add(
                PaymentLedger(
                    order_id=order.id,
                    amount=payment.amount,
                    transaction_type=TransactionType.REFUND,
                    status=LedgerStatus.COMPLETED,
                    reference=refund_reference(req.id),
                )
            )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    db.expire_all()
    return db.get(RefundRequest, request_id)
