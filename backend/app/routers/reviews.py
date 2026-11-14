from uuid import UUID
from fastapi import APIRouter, Query, Response

from app.dependencies import CustomerUser, DbSession
from app.schemas.review import PublicReviewRead, ReviewCreate, ReviewRead
from app.services import review_service as svc

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=ReviewRead, status_code=201)
def create_review(data: ReviewCreate, db: DbSession, customer: CustomerUser):
    """One review per delivered order, by the customer who placed it."""
    return svc.create_review(db, customer, data)


@router.get("/restaurant/{restaurant_id}", response_model=list[PublicReviewRead])
def restaurant_reviews(
    restaurant_id: UUID,
    db: DbSession,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return svc.list_restaurant_reviews(db, restaurant_id, limit, offset)


@router.delete("/{review_id}", status_code=204)
def delete_review(review_id: UUID, db: DbSession, customer: CustomerUser):
    svc.delete_review(db, customer, review_id)
    return Response(status_code=204)
