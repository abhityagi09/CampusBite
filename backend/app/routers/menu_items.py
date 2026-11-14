"""Public cross-restaurant menu search."""

from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies import DbSession
from app.dependencies.query import MenuFilterParams, PageParams
from app.schemas.common import Page
from app.schemas.restaurant import MenuItemSearchResult
from app.services import restaurant_service as svc

router = APIRouter(prefix="/menu-items", tags=["menu items"])


@router.get("", response_model=Page[MenuItemSearchResult])
def search_menu_items(
    db: DbSession,
    page: PageParams,
    filters: MenuFilterParams,
    restaurant_id: UUID | None = Query(None),
    open_only: bool = Query(False, description="Only restaurants currently accepting orders"),
):
    """Available items from active restaurants, sorted by name."""
    return svc.search_menu_items(db, filters, page, restaurant_id, open_only)
