from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.core.config import settings
from app.database.base import Base
from app.database.session import engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """Keep migration 0002's preserved legacy_* tables (and their indexes) out of autogenerate."""
    if type_ == "table" and reflected and name is not None:
        return not (name.startswith("legacy_"))
    if type_ in ("index", "unique_constraint", "foreign_key_constraint") and reflected:
        table = getattr(obj, "table", None)
        if table is not None and table.name.startswith("legacy_"):
            return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (alembic upgrade head --sql)."""
    context.configure(
        url=settings.sqlalchemy_url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Same URL and driver settings as the application, built from environment variables.
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
