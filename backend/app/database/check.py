"""Command-line connectivity and migration check.

    python -m app.database.check

Exit codes: 0 = connected and migrations are up to date,
            1 = cannot connect, 2 = connected but migrations are not applied.
"""

import sys
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.database.session import engine

BACKEND_DIR = Path(__file__).resolve().parents[2]


def main() -> int:
    print(f"Target : {settings.safe_database_url}")
    try:
        with engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                version = conn.execute(text("SELECT version()")).scalar()
                name = conn.execute(text("SELECT current_database()")).scalar()
            else:  # only happens if DATABASE_URL points somewhere else (e.g. tests)
                version = f"{conn.dialect.name} (not PostgreSQL)"
                name = conn.engine.url.database
            print(f"Connect: OK  (database '{name}')")
            print(f"Server : {version}")

            cfg = Config(str(BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
            heads = set(ScriptDirectory.from_config(cfg).get_heads())
            current = set(MigrationContext.configure(conn).get_current_heads())
            tables = sorted(t for t in inspect(conn).get_table_names() if t != "alembic_version")
    except SQLAlchemyError as exc:
        print("Connect: FAILED")
        print(f"Reason : {getattr(exc, 'orig', exc)}")
        print(
            "Hints  : is PostgreSQL running (docker compose ps)? Are POSTGRES_HOST/PORT/USER/"
            "PASSWORD/DB in backend/.env correct? Use localhost when running on your computer, "
            "db inside Docker."
        )
        return 1

    print(f"Tables : {len(tables)} ({', '.join(tables) or 'none'})")
    if current == heads and heads:
        print(f"Migrate: up to date (revision {', '.join(sorted(current))})")
        return 0
    print(
        f"Migrate: NOT up to date (database at {', '.join(sorted(current)) or 'nothing'}, "
        f"code at {', '.join(sorted(heads))}). Run: alembic upgrade head"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
