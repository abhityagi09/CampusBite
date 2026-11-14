"""Exhaustive order-transition matrix: every (from, to, actor) combination.

The expected set below is written out independently from the capstone brief, so this test
fails if order_lifecycle.TRANSITIONS ever drifts from the specification."""

import itertools

import pytest

from app.core.exceptions import ConflictError, ForbiddenError
from app.models import OrderStatus as S
from app.services.order_lifecycle import TERMINAL, TRANSITIONS, Actor, check_transition

ALLOWED = {
    (S.PENDING_PAYMENT, S.PLACED, Actor.SYSTEM),       # dummy payment succeeded
    (S.PENDING_PAYMENT, S.CANCELLED, Actor.CUSTOMER),  # unpaid, nothing charged
    (S.PLACED, S.ACCEPTED, Actor.OWNER),
    (S.PLACED, S.REJECTED, Actor.OWNER),
    (S.PLACED, S.CANCELLED, Actor.CUSTOMER),           # customers cancel only PLACED
    (S.ACCEPTED, S.PREPARING, Actor.OWNER),
    (S.ACCEPTED, S.REJECTED, Actor.OWNER),
    (S.PREPARING, S.READY, Actor.OWNER),
    (S.READY, S.ASSIGNED, Actor.OWNER),                # assignment only when READY
    (S.ASSIGNED, S.OUT_FOR_DELIVERY, Actor.COURIER),
    (S.OUT_FOR_DELIVERY, S.DELIVERED, Actor.COURIER),
    (S.DELIVERED, S.REFUNDED, Actor.SYSTEM),           # approved refund request
}
VALID_MOVES = {(a, b) for a, b, _ in ALLOWED}
CASES = list(itertools.product(S, S, Actor))


@pytest.mark.parametrize("current,new,actor", CASES, ids=[f"{a.value}->{b.value}:{c.value}" for a, b, c in CASES])
def test_transition(current, new, actor):
    if (current, new, actor) in ALLOWED:
        check_transition(current, new, actor)  # must not raise
    elif (current, new) in VALID_MOVES:
        with pytest.raises(ForbiddenError):  # real move, wrong actor -> 403
            check_transition(current, new, actor)
    else:
        with pytest.raises(ConflictError):  # skipped, reversed, repeated, from terminal -> 409
            check_transition(current, new, actor)


def test_matrix_size_and_terminal_states():
    assert len(CASES) == len(S) ** 2 * len(Actor)
    assert TERMINAL == {S.CANCELLED, S.REJECTED, S.REFUNDED} and not TERMINAL & set(TRANSITIONS)
    for terminal in (S.CANCELLED, S.REJECTED, S.REFUNDED):
        assert not any(a == terminal for a, _, _ in ALLOWED)
    assert not any(b == S.CANCELLED and a == S.DELIVERED for a, b, _ in ALLOWED)  # delivered can't be cancelled
