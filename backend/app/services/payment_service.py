import uuid
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import ensure_role
from app.models import (
    LedgerStatus,
    OrderStatus,
    Payment,
    PaymentLedger,
    PaymentStatus,
    TransactionType,
    User,
    UserRole,
)
from app.schemas.payment import PaymentCreate
from app.services import order_service


def pay_order(db: Session, customer: User, order_id: UUID, data: PaymentCreate) -> Payment:
    """Simulated gateway: always succeeds unless simulate_failure is set.
    A failed attempt keeps the order in pending_payment so the customer can retry."""
    ensure_role(customer, UserRole.CUSTOMER)
    order = order_service.load_order(db, order_id, lock=True)
    if order is None or order.customer_id != customer.id:
        raise NotFoundError("Order not found")
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise ConflictError(f"Order is '{order.status.value}', not awaiting payment")

    payment = order.payment
    if payment is None:
        payment = Payment(order_id=order.id, amount=order.total_amount, method=data.method)
        db.add(payment)
        order.payment = payment
    payment.method = data.method

    if data.simulate_failure:
        payment.status = PaymentStatus.FAILED
        payment.transaction_ref = None
        payment.failure_reason = "Payment declined (simulated)"
        order.ledger_entries.append(
            PaymentLedger(
                amount=order.total_amount,
                transaction_type=TransactionType.CHARGE,
                status=LedgerStatus.FAILED,
                reference=None,
            )
        )
    else:
        payment.status = PaymentStatus.PAID
        payment.transaction_ref = f"SIM-{uuid.uuid4().hex[:16].upper()}"
        payment.failure_reason = None
        order.ledger_entries.append(
            PaymentLedger(
                amount=order.total_amount,
                transaction_type=TransactionType.CHARGE,
                status=LedgerStatus.COMPLETED,
                reference=payment.transaction_ref,
            )
        )
        order_service.apply_status(order, OrderStatus.PLACED, customer)

    db.commit()
    db.refresh(payment)
    return payment


def get_payment(db: Session, user: User, order_id: UUID) -> Payment:
    if user.role not in (UserRole.CUSTOMER, UserRole.OWNER):
        raise NotFoundError("Payment not found")
    order = order_service.get_order_for_user(db, order_id, user)
    if order.payment is None:
        raise NotFoundError("No payment has been made for this order")
    return order.payment


def get_ledger(db: Session, user: User, order_id: UUID) -> list[PaymentLedger]:
    """Money history of an order (same visibility rules as get_payment)."""
    if user.role not in (UserRole.CUSTOMER, UserRole.OWNER):
        raise NotFoundError("Payment not found")
    order = order_service.get_order_for_user(db, order_id, user)
    return list(order.ledger_entries)
