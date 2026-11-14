"""Sample data for local development.

    python -m app.seed            (inside the backend container:  docker compose exec backend python -m app.seed)

Idempotent: users are matched by e-mail and restaurants by (owner, name), so running it
again adds nothing. Refuses to run when ENVIRONMENT=production.
Every account's password is SEED_PASSWORD below (development only).
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.database.session import SessionLocal
from app.models import MenuItem, Restaurant, User, UserRole

SEED_PASSWORD = "Campus123"

USERS = [
    ("Asha Customer", "asha@example.com", UserRole.CUSTOMER),
    ("Ben Customer", "ben@example.com", UserRole.CUSTOMER),
    ("Chen Customer", "chen@example.com", UserRole.CUSTOMER),
    ("Grill Owner", "grill.owner@example.com", UserRole.OWNER),
    ("Dosa Owner", "dosa.owner@example.com", UserRole.OWNER),
    ("Dev Courier", "dev.courier@example.com", UserRole.DELIVERY_PARTNER),
    ("Eva Courier", "eva.courier@example.com", UserRole.DELIVERY_PARTNER),
]

RESTAURANTS = [
    ("grill.owner@example.com", "Campus Grill", "American", "Block A, Ground floor", [
        ("Classic Burger", "Mains", "5.50"), ("Veggie Burger", "Mains", "5.00"),
        ("Fries", "Sides", "2.25"), ("Cola", "Drinks", "1.50"),
    ]),
    ("grill.owner@example.com", "Late Night Bites", "Snacks", "Hostel 2 Lobby", [
        ("Cheese Toastie", "Snacks", "3.00"), ("Instant Noodles", "Snacks", "2.50"),
        ("Cold Coffee", "Drinks", "2.00"),
    ]),
    ("dosa.owner@example.com", "Dosa Corner", "South Indian", "Library Lane", [
        ("Masala Dosa", "Mains", "4.00"), ("Idli (3 pcs)", "Mains", "3.00"),
        ("Filter Coffee", "Drinks", "1.20"), ("Vada", "Sides", "1.50"),
    ]),
]


def seed(db: Session) -> dict[str, int]:
    created = {"users": 0, "restaurants": 0, "menu_items": 0}
    users: dict[str, User] = {}
    password_hash = hash_password(SEED_PASSWORD)
    for name, email, role in USERS:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(name=name, email=email, role=role, password_hash=password_hash)
            db.add(user)
            created["users"] += 1
        users[email] = user
    db.flush()

    for owner_email, name, cuisine, location, items in RESTAURANTS:
        owner = users[owner_email]
        restaurant = db.scalar(
            select(Restaurant).where(Restaurant.owner_id == owner.id, Restaurant.name == name)
        )
        if restaurant is None:
            restaurant = Restaurant(owner_id=owner.id, name=name, cuisine=cuisine, location=location)
            db.add(restaurant)
            db.flush()
            created["restaurants"] += 1
            for item_name, category, price in items:
                db.add(MenuItem(restaurant_id=restaurant.id, name=item_name,
                                category=category, price=Decimal(price)))
                created["menu_items"] += 1
    db.commit()
    return created


def main() -> None:
    if settings.ENVIRONMENT.lower() == "production":
        raise SystemExit("Refusing to seed a production database.")
    with SessionLocal() as db:
        created = seed(db)
    print(f"Seeded: {created}. All accounts use the password {SEED_PASSWORD!r}.")


if __name__ == "__main__":
    main()
