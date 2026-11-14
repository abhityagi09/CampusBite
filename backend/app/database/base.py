from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names. Without this PostgreSQL invents names, and future
# Alembic migrations that drop or alter a constraint have nothing stable to refer to.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    Every model must be imported in app/models/__init__.py. Alembic's env.py imports
    that package, which is what registers the tables on Base.metadata.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
