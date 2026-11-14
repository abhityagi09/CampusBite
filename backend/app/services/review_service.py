from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.permissions import ensure_role
from app.models import Order, OrderStatus, Restaurant, Review, User, UserRole
from app.schemas.common import Page
from app.schemas.review import PublicReviewRead, ReviewCreate
from app.services.restaurant_service import Pagination


def create_review(db: Session, customer: User, data: ReviewCreate) -> Review:
    ensure_role(customer, UserRole.CUSTOMER)
    order = db.get(Order, data.order_id)
    if order is None or order.customer_id != customer.id:
        raise NotFoundError("Order not found")
    if order.status != OrderStatus.DELIVERED:
        raise BadRequestError("Only delivered orders can be reviewed")
    if db.scalar(select(Review.id).where(Review.order_id == order.id)):
        raise ConflictError("This order has already been reviewed")

    review = Review(
        order_id=order.id,
        customer_id=customer.id,
        restaurant_id=order.restaurant_id,
        rating=data.rating,
        comment=data.comment,
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("This order has already been reviewed") from None
    db.refresh(review)
    return review


def list_restaurant_reviews(
    db: Session, restaurant_id: UUID, limit: int, offset: int
) -> list[Review]:
    if db.get(Restaurant, restaurant_id) is None:
        raise NotFoundError("Restaurant not found")
    return list(
        db.scalars(
            select(Review)
            .where(Review.restaurant_id == restaurant_id)
            .order_by(Review.created_at.desc(), Review.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )


def delete_review(db: Session, customer: User, review_id: UUID) -> None:
    review = db.get(Review, review_id)
    if review is None or review.customer_id != customer.id:
        raise NotFoundError("Review not found")
    db.delete(review)
    db.commit()


def list_public_reviews(db: Session, restaurant_id: UUID, page: Pagination) -> Page[PublicReviewRead]:
    """Reviews of an ACTIVE restaurant, newest first, without private ids."""
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None or not restaurant.is_active:
        raise NotFoundError("Restaurant not found")
    stmt = (
        select(Review)
        .where(Review.restaurant_id == restaurant_id)
        .order_by(Review.created_at.desc(), Review.id.desc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[PublicReviewRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
