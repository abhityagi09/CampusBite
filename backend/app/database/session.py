import logging
import time
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger("campusbite.db")


def create_db_engine(url: URL) -> Engine:
    """Build the engine. Connections are opened lazily, so importing this module
    never needs a running database."""
    options: dict = {"pool_pre_ping": True}  # drop dead connections (DB restarted etc.)
    if url.get_backend_name() == "postgresql":
        options.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT},
        )
    return create_engine(url, **options)


engine = create_db_engine(settings.sqlalchemy_url)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request.

    Rolls back if the request fails part-way and always returns the connection
    to the pool."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_connection(target: Engine | None = None) -> None:
    """Run SELECT 1. Raises SQLAlchemyError if the database is unreachable."""
    with (target or engine).connect() as conn:
        conn.execute(text("SELECT 1"))


def wait_for_database(
    retries: int | None = None, delay: float | None = None
) -> bool:
    """Try to connect, retrying while PostgreSQL is still starting up."""
    attempts = retries if retries is not None else settings.DB_STARTUP_RETRIES
    pause = delay if delay is not None else settings.DB_STARTUP_RETRY_DELAY
    for attempt in range(1, attempts + 1):
        try:
            check_connection()
            return True
        except SQLAlchemyError as exc:
            logger.warning(
                "Database not reachable (attempt %d/%d): %s",
                attempt,
                attempts,
                getattr(exc, "orig", exc),
            )
            if attempt < attempts:
                time.sleep(pause)
    return False
