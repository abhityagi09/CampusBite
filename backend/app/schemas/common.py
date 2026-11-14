from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One page of a list endpoint. ``total`` counts every match, not just this page."""

    items: list[T]
    total: int
    limit: int
    offset: int
