"""Restaurant and menu endpoints.

Public (no login): browse/search restaurants, restaurant detail, a restaurant's menu.
Owner only: create/update own restaurants, manage their menu items, see everything they
own including inactive restaurants and disabled items. Other roles get 403; another
owner's restaurant gets 403; missing ids get 404.
"""

from dataclasses import replace
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.dependencies import DbSession, OwnerUser
from app.dependencies.query import MenuFilterParams, PageParams
from app.schemas.common import Page
from app.schemas.restaurant import (
    MenuItemCreate,
    MenuItemRead,
    MenuItemUpdate,
    RestaurantCreate,
    RestaurantDetail,
    RestaurantRead,
    RestaurantUpdate,
)
from app.schemas.review import PublicReviewRead
from app.services import restaurant_service as svc
from app.services import review_service as review_svc
from app.services.restaurant_service import RestaurantFilters

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


# ---- public ------------------------------------------------------------------


@router.get("", response_model=Page[RestaurantRead])
def list_restaurants(
    db: DbSession,
    page: PageParams,
    q: str | None = Query(None, min_length=1, max_length=100, description="Search name, cuisine or description"),
    cuisine: str | None = Query(None, max_length=60, description="Exact cuisine (case-insensitive)"),
    location: str | None = Query(None, max_length=200),
    open_only: bool = False,
):
    """Active restaurants, sorted by name."""
    filters = RestaurantFilters(q=q, cuisine=cuisine, location=location, open_only=open_only)
    return svc.list_restaurants(db, filters, page)


# ---- owner -------------------------------------------------------------------
# "/mine..." routes must be declared before "/{restaurant_id}".


@router.post("", response_model=RestaurantRead, status_code=201)
def create_restaurant(data: RestaurantCreate, db: DbSession, owner: OwnerUser):
    return svc.create_restaurant(db, owner, data)


@router.get("/mine", response_model=Page[RestaurantDetail])
def my_restaurants(db: DbSession, owner: OwnerUser, page: PageParams):
    """The owner's restaurants (including inactive) with every menu item."""
    return svc.list_owner_restaurants(db, owner, page)


@router.get("/mine/menu-items", response_model=Page[MenuItemRead])
def my_menu_items(
    db: DbSession,
    owner: OwnerUser,
    page: PageParams,
    filters: MenuFilterParams,
    restaurant_id: UUID | None = Query(None, description="Only this (owned) restaurant"),
    is_available: bool | None = Query(None, description="Filter by availability"),
):
    """Every menu item across the owner's restaurants, including disabled ones."""
    filters = replace(filters, is_available=is_available)
    return svc.list_owner_menu_items(db, owner, filters, page, restaurant_id)


# ---- public (by id) ----------------------------------------------------------


@router.get("/{restaurant_id}", response_model=RestaurantDetail)
def get_restaurant(restaurant_id: UUID, db: DbSession):
    """An active restaurant with its available menu items."""
    return svc.get_restaurant(db, restaurant_id)


@router.get("/{restaurant_id}/menu", response_model=Page[MenuItemRead])
def list_menu(
    restaurant_id: UUID, db: DbSession, page: PageParams, filters: MenuFilterParams
):
    """Available items of an active restaurant. Owners use /restaurants/mine/menu-items
    to also see disabled items."""
    return svc.list_menu(db, restaurant_id, filters, page)


# ---- owner (by id) -----------------------------------------------------------


@router.patch("/{restaurant_id}", response_model=RestaurantRead)
def update_restaurant(
    restaurant_id: UUID, data: RestaurantUpdate, db: DbSession, owner: OwnerUser
):
    return svc.update_restaurant(db, owner, restaurant_id, data)


@router.post("/{restaurant_id}/menu", response_model=MenuItemRead, status_code=201)
def add_menu_item(
    restaurant_id: UUID, data: MenuItemCreate, db: DbSession, owner: OwnerUser
):
    return svc.add_menu_item(db, owner, restaurant_id, data)


@router.patch("/{restaurant_id}/menu/{item_id}", response_model=MenuItemRead)
def update_menu_item(
    restaurant_id: UUID,
    item_id: UUID,
    data: MenuItemUpdate,
    db: DbSession,
    owner: OwnerUser,
):
    return svc.update_menu_item(db, owner, restaurant_id, item_id, data)


@router.post("/{restaurant_id}/menu/{item_id}/disable", response_model=MenuItemRead)
def disable_menu_item(restaurant_id: UUID, item_id: UUID, db: DbSession, owner: OwnerUser):
    """Hide the item from customers and block new orders for it (idempotent)."""
    return svc.set_menu_item_availability(db, owner, restaurant_id, item_id, False)


@router.post("/{restaurant_id}/menu/{item_id}/enable", response_model=MenuItemRead)
def enable_menu_item(restaurant_id: UUID, item_id: UUID, db: DbSession, owner: OwnerUser):
    """Make the item orderable again (idempotent)."""
    return svc.set_menu_item_availability(db, owner, restaurant_id, item_id, True)


@router.delete("/{restaurant_id}/menu/{item_id}", status_code=204)
def delete_menu_item(restaurant_id: UUID, item_id: UUID, db: DbSession, owner: OwnerUser):
    """Remove an item from the menu. Items that appear in past orders are soft-disabled
    (kept, with is_available=false) rather than deleted, so order history stays intact."""
    svc.delete_menu_item(db, owner, restaurant_id, item_id)
    return Response(status_code=204)


@router.get("/{restaurant_id}/reviews", response_model=Page[PublicReviewRead])
def restaurant_reviews(restaurant_id: UUID, db: DbSession, page: PageParams):
    """Public reviews, newest first. Reviewer and order ids are not exposed."""
    return review_svc.list_public_reviews(db, restaurant_id, page)
