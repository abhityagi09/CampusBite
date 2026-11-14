from fastapi import APIRouter

from app.routers import (
    ai,
    auth,
    deliveries,
    menu_items,
    orders,
    owner_reminders,
    payments,
    refunds,
    restaurants,
    reviews,
    statistics,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(restaurants.router)
api_router.include_router(menu_items.router)
api_router.include_router(orders.router)
api_router.include_router(deliveries.router)
api_router.include_router(payments.router)
api_router.include_router(reviews.router)
api_router.include_router(refunds.router)
api_router.include_router(statistics.router)
api_router.include_router(users.router)
api_router.include_router(owner_reminders.router)
api_router.include_router(ai.router)
