"""Reusable query-string parameters for list endpoints."""

from decimal import Decimal
from typing import Annotated

from fastapi import Depends, Query

from app.services.restaurant_service import MenuFilters, Pagination


def pagination(
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


def menu_filters(
    q: str | None = Query(
        None, min_length=1, max_length=100, description="Search name, description or category"
    ),
    category: str | None = Query(None, max_length=60, description="Exact category (case-insensitive)"),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
) -> MenuFilters:
    return MenuFilters(q=q, category=category, min_price=min_price, max_price=max_price)


PageParams = Annotated[Pagination, Depends(pagination)]
MenuFilterParams = Annotated[MenuFilters, Depends(menu_filters)]
