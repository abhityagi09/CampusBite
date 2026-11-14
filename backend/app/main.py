import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.exceptions import AppError
from app.database.session import check_connection, engine, wait_for_database
from app.routers import api_router

logger = logging.getLogger("campusbite")
access_log = logging.getLogger("campusbite.access")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tables are NOT created here: the schema is managed only by `alembic upgrade head`.
    # We just check connectivity (retrying while PostgreSQL boots) and log the result.
    # If the database is still down the API starts anyway; /health/db reports it
    # and database-backed endpoints answer 503 until it is back.
    reachable = await run_in_threadpool(wait_for_database)
    if reachable:
        logger.info("Connected to database %s", settings.safe_database_url)
    else:
        logger.error(
            "Could not reach database %s - API started, DB endpoints return 503",
            settings.safe_database_url,
        )
    # Reminders are NOT scheduled here: the dedicated worker (`python -m app.worker`, the
    # `scheduler` Compose service) runs them, so API workers never duplicate the job.
    yield
    engine.dispose()


def configure_logging() -> None:
    """Uvicorn only configures its own loggers; give ours (access log, AI, worker) a handler
    so INFO lines such as "GET /api/v1/orders -> 200 (12.3 ms)" actually reach the console."""
    app_log = logging.getLogger("campusbite")
    if not app_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        app_log.addHandler(handler)
    app_log.setLevel(logging.INFO)


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.3.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # readable by the browser app (rate-limit waits, idempotent replays, timing)
        expose_headers=["Retry-After", "Idempotent-Replayed", "X-Process-Time-Ms"],
    )

    @app.middleware("http")
    async def log_and_time_requests(request: Request, call_next):
        """Access log (method, path, status, duration) + X-Process-Time-Ms header.
        Only the path is logged: query strings and bodies may hold personal data."""
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            access_log.error("%s %s -> 500 (%.1f ms)", request.method, request.url.path,
                             (time.perf_counter() - start) * 1000)
            raise
        elapsed = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{elapsed:.1f}"
        access_log.info("%s %s -> %s (%.1f ms)", request.method, request.url.path,
                        response.status_code, elapsed)
        return response

    register_exception_handlers(app)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness: the API process is up (does not touch the database)."""
        return {"status": "ok", "environment": settings.ENVIRONMENT}

    @app.get("/health/db", tags=["health"])
    def health_db() -> JSONResponse:
        """Readiness: the API can reach PostgreSQL."""
        try:
            check_connection(engine)
        except SQLAlchemyError as exc:
            logger.error("Database health check failed: %s", getattr(exc, "orig", exc))
            return JSONResponse(
                status_code=503,
                content={"status": "error", "database": "unreachable"},
                headers={"Retry-After": "5"},
            )
        return JSONResponse(content={"status": "ok", "database": "connected"})

    app.include_router(api_router, prefix="/api/v1")
    return app


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                {"detail": "Validation error", "errors": exc.errors()}
            ),
        )

    async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
        # Connection refused, DB restarting, auth failure, pool exhausted, timeouts...
        logger.error(
            "Database unavailable on %s %s: %s",
            request.method,
            request.url.path,
            getattr(exc, "orig", exc),
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Database temporarily unavailable. Please try again shortly."},
            headers={"Retry-After": "5"},
        )

    for exc_class in (OperationalError, InterfaceError, PoolTimeoutError):
        app.add_exception_handler(exc_class, database_unavailable_handler)

    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        logger.exception("Database error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Database error"})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )


app = create_app()
