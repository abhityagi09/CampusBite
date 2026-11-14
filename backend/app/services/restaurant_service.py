"""Restaurants and menus: browsing, search and owner management.

Visibility rules (enforced here, not in the routers):
* Public / customers see only ACTIVE restaurants and only AVAILABLE menu items.
* Owners see everything that belongs to them, including inactive restaurants and
  disabled items, through the owner-only functions.
* Writes require the OWNER role *and* ownership of the restaurant (403 otherwise).

Menu items are never hard-deleted once an order references them: order history keeps a
snapshot of name/price, but statistics and audits still join on menu_item_id, so such
items are soft-disabled (is_available = False) instead.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ForbiddenError, NotFoundError, UnprocessableError
from app.core.permissions import ensure_role
from app.models import MenuItem, OrderItem, Restaurant, Review, User, UserRole
from app.schemas.common import Page
from app.schemas.restaurant import (
    MenuItemCreate,
    MenuItemRead,
    MenuItemSearchResult,
    MenuItemUpdate,
    RestaurantCreate,
    RestaurantDetail,
    RestaurantRead,
    RestaurantUpdate,
)


@dataclass(frozen=True)
class Pagination:
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True)
class RestaurantFilters:
    q: str | None = None  # matches name, cuisine or description
    cuisine: str | None = None  # exact, case-insensitive
    location: str | None = None  # substring, case-insensitive
    open_only: bool = False


@dataclass(frozen=True)
class MenuFilters:
    q: str | None = None  # matches name, description or category
    category: str | None = None  # exact, case-insensitive
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    # Owner views only; public views always force available items.
    is_available: bool | None = None

    def __post_init__(self):
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise UnprocessableError("min_price cannot be greater than max_price")


# ---- helpers ---------------------------------------------------------------


def _icontains(column, text: str):
    return func.lower(column).contains(text.lower(), autoescape=True)


def _paginate(db: Session, stmt: Select, page: Pagination) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return list(rows), total or 0


def _ratings(db: Session, restaurant_ids: list[UUID]) -> dict[UUID, tuple[float, int]]:
    if not restaurant_ids:
        return {}
    rows = db.execute(
        select(Review.restaurant_id, func.avg(Review.rating), func.count(Review.id))
        .where(Review.restaurant_id.in_(restaurant_ids))
        .group_by(Review.restaurant_id)
    ).all()
    return {rid: (round(float(avg), 2), count) for rid, avg, count in rows}


def _to_read(
    restaurant: Restaurant, ratings: dict[UUID, tuple[float, int]]
) -> RestaurantRead:
    avg, count = ratings.get(restaurant.id, (None, 0))
    read = RestaurantRead.model_validate(restaurant)
    return read.model_copy(update={"average_rating": avg, "review_count": count})


def _to_detail(
    restaurant: Restaurant,
    ratings: dict[UUID, tuple[float, int]],
    include_unavailable: bool,
) -> RestaurantDetail:
    base = _to_read(restaurant, ratings)
    items = [
        MenuItemRead.model_validate(m)
        for m in restaurant.menu_items
        if include_unavailable or m.is_available
    ]
    return RestaurantDetail(**base.model_dump(), menu_items=items)


def _apply_restaurant_filters(stmt: Select, f: RestaurantFilters) -> Select:
    if f.q:
        stmt = stmt.where(
            or_(
                _icontains(Restaurant.name, f.q),
                _icontains(Restaurant.cuisine, f.q),
                _icontains(Restaurant.description, f.q),
            )
        )
    if f.cuisine:
        stmt = stmt.where(func.lower(Restaurant.cuisine) == f.cuisine.lower())
    if f.location:
        stmt = stmt.where(_icontains(Restaurant.location, f.location))
    if f.open_only:
        stmt = stmt.where(Restaurant.is_open.is_(True))
    return stmt


def _apply_menu_filters(stmt: Select, f: MenuFilters) -> Select:
    if f.q:
        stmt = stmt.where(
            or_(
                _icontains(MenuItem.name, f.q),
                _icontains(MenuItem.description, f.q),
                _icontains(MenuItem.category, f.q),
            )
        )
    if f.category:
        stmt = stmt.where(func.lower(MenuItem.category) == f.category.lower())
    if f.min_price is not None:
        stmt = stmt.where(MenuItem.price >= f.min_price)
    if f.max_price is not None:
        stmt = stmt.where(MenuItem.price <= f.max_price)
    if f.is_available is not None:
        stmt = stmt.where(MenuItem.is_available.is_(f.is_available))
    return stmt


def _get_active_restaurant(db: Session, restaurant_id: UUID) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None or not restaurant.is_active:
        raise NotFoundError("Restaurant not found")
    return restaurant


def _get_owned_restaurant(db: Session, restaurant_id: UUID, owner: User) -> Restaurant:
    ensure_role(owner, UserRole.OWNER)
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")
    if restaurant.owner_id != owner.id:
        raise ForbiddenError("You do not own this restaurant")
    return restaurant


def _get_owned_item(db: Session, owner: User, restaurant_id: UUID, item_id: UUID) -> MenuItem:
    _get_owned_restaurant(db, restaurant_id, owner)
    item = db.get(MenuItem, item_id)
    if item is None or item.restaurant_id != restaurant_id:
        raise NotFoundError("Menu item not found")
    return item


# ---- restaurants: public ---------------------------------------------------


def list_restaurants(
    db: Session, filters: RestaurantFilters, page: Pagination
) -> Page[RestaurantRead]:
    stmt = _apply_restaurant_filters(
        select(Restaurant)
        .where(Restaurant.is_active.is_(True))
        .order_by(Restaurant.name, Restaurant.created_at, Restaurant.id),
        filters,
    )
    restaurants, total = _paginate(db, stmt, page)
    ratings = _ratings(db, [r.id for r in restaurants])
    return Page(
        items=[_to_read(r, ratings) for r in restaurants],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def get_restaurant(db: Session, restaurant_id: UUID) -> RestaurantDetail:
    restaurant = db.scalar(
        select(Restaurant)
        .options(selectinload(Restaurant.menu_items))
        .where(Restaurant.id == restaurant_id)
    )
    if restaurant is None or not restaurant.is_active:
        raise NotFoundError("Restaurant not found")
    return _to_detail(restaurant, _ratings(db, [restaurant.id]), include_unavailable=False)


# ---- restaurants: owner ----------------------------------------------------


def create_restaurant(db: Session, owner: User, data: RestaurantCreate) -> RestaurantRead:
    ensure_role(owner, UserRole.OWNER)
    restaurant = Restaurant(owner_id=owner.id, **data.model_dump())
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return _to_read(restaurant, {})


def update_restaurant(
    db: Session, owner: User, restaurant_id: UUID, data: RestaurantUpdate
) -> RestaurantRead:
    restaurant = _get_owned_restaurant(db, restaurant_id, owner)
    # The schema already rejected null for required columns, so a null here means
    # "clear this optional field".
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(restaurant, key, value)
    db.commit()
    db.refresh(restaurant)
    return _to_read(restaurant, _ratings(db, [restaurant.id]))


def list_owner_restaurants(
    db: Session, owner: User, page: Pagination
) -> Page[RestaurantDetail]:
    """The owner's restaurants (active or not) with every menu item."""
    ensure_role(owner, UserRole.OWNER)
    stmt = (
        select(Restaurant)
        .options(selectinload(Restaurant.menu_items))
        .where(Restaurant.owner_id == owner.id)
        .order_by(Restaurant.created_at, Restaurant.id)
    )
    restaurants, total = _paginate(db, stmt, page)
    ratings = _ratings(db, [r.id for r in restaurants])
    return Page(
        items=[_to_detail(r, ratings, include_unavailable=True) for r in restaurants],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# ---- menu items: public ----------------------------------------------------


def list_menu(
    db: Session, restaurant_id: UUID, filters: MenuFilters, page: Pagination
) -> Page[MenuItemRead]:
    """Available items of an active restaurant. ``filters.is_available`` is ignored."""
    _get_active_restaurant(db, restaurant_id)
    stmt = _apply_menu_filters(
        select(MenuItem)
        .where(MenuItem.restaurant_id == restaurant_id, MenuItem.is_available.is_(True))
        .order_by(MenuItem.created_at, MenuItem.id),
        replace(filters, is_available=None),
    )
    items, total = _paginate(db, stmt, page)
    return Page(
        items=[MenuItemRead.model_validate(i) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def search_menu_items(
    db: Session,
    filters: MenuFilters,
    page: Pagination,
    restaurant_id: UUID | None = None,
    open_only: bool = False,
) -> Page[MenuItemSearchResult]:
    """Search available items across all active restaurants."""
    stmt = (
        select(MenuItem, Restaurant)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .where(Restaurant.is_active.is_(True), MenuItem.is_available.is_(True))
        .order_by(MenuItem.name, MenuItem.created_at, MenuItem.id)
    )
    stmt = _apply_menu_filters(stmt, replace(filters, is_available=None))
    if restaurant_id is not None:
        stmt = stmt.where(MenuItem.restaurant_id == restaurant_id)
    if open_only:
        stmt = stmt.where(Restaurant.is_open.is_(True))

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[
            MenuItemSearchResult(
                **MenuItemRead.model_validate(item).model_dump(),
                restaurant_name=restaurant.name,
                restaurant_is_open=restaurant.is_open,
            )
            for item, restaurant in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# ---- menu items: owner -----------------------------------------------------


def list_owner_menu_items(
    db: Session,
    owner: User,
    filters: MenuFilters,
    page: Pagination,
    restaurant_id: UUID | None = None,
) -> Page[MenuItemRead]:
    """Every item (available or not) across the owner's restaurants."""
    ensure_role(owner, UserRole.OWNER)
    if restaurant_id is not None:
        _get_owned_restaurant(db, restaurant_id, owner)  # 404 / 403 for a foreign one
    stmt = (
        select(MenuItem)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .where(Restaurant.owner_id == owner.id)
        .order_by(MenuItem.restaurant_id, MenuItem.created_at, MenuItem.id)
    )
    if restaurant_id is not None:
        stmt = stmt.where(MenuItem.restaurant_id == restaurant_id)
    items, total = _paginate(db, _apply_menu_filters(stmt, filters), page)
    return Page(
        items=[MenuItemRead.model_validate(i) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def add_menu_item(
    db: Session, owner: User, restaurant_id: UUID, data: MenuItemCreate
) -> MenuItem:
    restaurant = _get_owned_restaurant(db, restaurant_id, owner)
    item = MenuItem(restaurant_id=restaurant.id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_menu_item(
    db: Session, owner: User, restaurant_id: UUID, item_id: UUID, data: MenuItemUpdate
) -> MenuItem:
    item = _get_owned_item(db, owner, restaurant_id, item_id)
    # Past orders keep their own name/price snapshot, so edits never rewrite history.
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


def set_menu_item_availability(
    db: Session, owner: User, restaurant_id: UUID, item_id: UUID, available: bool
) -> MenuItem:
    item = _get_owned_item(db, owner, restaurant_id, item_id)
    item.is_available = available
    db.commit()
    db.refresh(item)
    return item


def is_menu_item_ordered(db: Session, item_id: UUID) -> bool:
    return bool(db.scalar(select(exists().where(OrderItem.menu_item_id == item_id))))


def delete_menu_item(db: Session, owner: User, restaurant_id: UUID, item_id: UUID) -> bool:
    """Remove an item from the menu.

    Never-ordered items are deleted outright. Items referenced by any historical order are
    soft-disabled instead, so order history keeps pointing at a real row.
    Returns True if the row was deleted, False if it was soft-disabled.
    """
    item = _get_owned_item(db, owner, restaurant_id, item_id)
    if is_menu_item_ordered(db, item.id):
        item.is_available = False
        db.commit()
        return False
    db.delete(item)
    db.commit()
    return True
