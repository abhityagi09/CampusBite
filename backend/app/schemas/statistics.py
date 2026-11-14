from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TopItem(BaseModel):
    name: str
    quantity: int


class RestaurantPerformance(BaseModel):
    restaurant_id: UUID
    name: str
    is_active: bool
    total_orders: int
    delivered_orders: int
    cancelled_or_rejected: int
    revenue: Decimal  # delivered orders, before refunds
    average_rating: float | None
    review_count: int


class CustomerRestaurantSummary(BaseModel):
    restaurant_id: UUID
    name: str
    order_count: int
    spent: Decimal  # delivered orders


class CustomerStats(BaseModel):
    role: Literal["customer"] = "customer"
    total_orders: int
    orders_by_status: dict[str, int]
    total_spent: Decimal  # delivered orders
    total_refunded: Decimal = Decimal("0.00")  # refunds on delivered orders
    net_spent: Decimal = Decimal("0.00")
    top_restaurants: list[CustomerRestaurantSummary] = []


class OwnerStats(BaseModel):
    role: Literal["owner"] = "owner"
    restaurant_count: int
    total_orders: int
    orders_by_status: dict[str, int]
    revenue: Decimal  # delivered orders, before refunds
    refunded: Decimal = Decimal("0.00")  # refunds on delivered orders
    net_revenue: Decimal = Decimal("0.00")
    average_rating: float | None
    review_count: int
    top_items: list[TopItem]
    restaurants: list[RestaurantPerformance] = []


class DeliveryStats(BaseModel):
    role: Literal["delivery_partner"] = "delivery_partner"
    completed_deliveries: int
    active_deliveries: int
    available_orders: int


Statistics = Annotated[
    CustomerStats | OwnerStats | DeliveryStats, Field(discriminator="role")
]
