from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

_INSECURE_DEFAULT_KEY = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "CampusBite API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # --- PostgreSQL -------------------------------------------------------
    # Normal setup: provide the POSTGRES_* parts. The URL is built from them, so
    # special characters in the password are escaped correctly.
    #   - on your computer:         POSTGRES_HOST=localhost
    #   - inside Docker Compose:    POSTGRES_HOST=db   (set by docker-compose.yml)
    # DATABASE_URL is an optional full override (e.g. a managed cloud database).
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: SecretStr | None = None
    POSTGRES_DB: str | None = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str | None = None

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 10  # seconds to wait for a free pooled connection
    DB_POOL_RECYCLE: int = 1800  # recycle connections after 30 minutes
    DB_CONNECT_TIMEOUT: int = 5  # seconds to wait when opening a connection
    DB_STARTUP_RETRIES: int = 5
    DB_STARTUP_RETRY_DELAY: float = 2.0

    # --- Auth -------------------------------------------------------------
    SECRET_KEY: str = _INSECURE_DEFAULT_KEY
    JWT_ALGORITHM: str = "HS256"
    # How long a token is valid. Bounded so a typo cannot create immortal tokens.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=1, le=1440)
    JWT_ISSUER: str = "campusbite-api"
    BCRYPT_ROUNDS: int = Field(default=12, ge=4, le=18)
    # Public registration only ever creates customers. Creating an owner or a delivery
    # partner requires this shared key in the X-Registration-Key header. Unset (the
    # default) means privileged registration is disabled entirely.
    STAFF_REGISTRATION_KEY: SecretStr | None = None

    # --- Simulated payments ---------------------------------------------------
    # There is no real gateway. The dummy gateway's outcome is chosen HERE, on the server,
    # never by the client: "success", "decline" (402, nothing saved) or "error" (502,
    # nothing saved). PAYMENT_SIMULATOR_METHOD_OUTCOMES overrides it per method,
    # e.g. "wallet=decline,card=error".
    PAYMENT_SIMULATOR_OUTCOME: Literal["success", "decline", "error"] = "success"
    PAYMENT_SIMULATOR_METHOD_OUTCOMES: str = ""

    # --- Reminders ------------------------------------------------------------
    # Dedicated reminder worker (`python -m app.worker`, the `scheduler` Compose service).
    REMINDER_SCHEDULER_ENABLED: bool = True
    ORDER_REMINDER_CHECK_INTERVAL_SECONDS: int = Field(default=60, ge=5, le=3600)
    # Owner reminder when an order stays placed/accepted for MORE than this many minutes.
    ORDER_REMINDER_THRESHOLD_MINUTES: int = Field(default=15, ge=1, le=1440)

    # --- AI insights (OpenAI, called from the backend only) -------------------
    OPENAI_API_KEY: SecretStr | None = None
    OPENAI_MODEL: str = "gpt-4.1-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_TIMEOUT_SECONDS: float = Field(default=30, gt=0, le=120)
    OPENAI_MAX_RETRIES: int = Field(default=2, ge=0, le=5)  # SDK retries, bounded
    # Per-customer AI budget: at most N requests per sliding window (both AI endpoints).
    AI_RATE_LIMIT_REQUESTS: int = Field(default=10, ge=1, le=1000)
    AI_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=3600, ge=1, le=86400)

    # Comma-separated list, e.g. "http://localhost:3000,http://localhost:5173"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @field_validator(
        "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "DATABASE_URL", "OPENAI_API_KEY", mode="before"
    )
    @classmethod
    def _empty_means_unset(cls, value):
        # docker-compose sets DATABASE_URL="" to neutralise a stale value in .env
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("JWT_ALGORITHM")
    @classmethod
    def _symmetric_algorithms_only(cls, value: str) -> str:
        # Never "none", and never an asymmetric algorithm with a shared secret.
        if value not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be HS256, HS384 or HS512")
        return value

    @field_validator("STAFF_REGISTRATION_KEY", mode="before")
    @classmethod
    def _empty_staff_key_means_disabled(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def _empty_secret_key_is_insecure_default(cls, value):
        # `SECRET_KEY=` (empty) in .env must not become a real, empty signing key.
        # Mapping it to the placeholder lets the production check below reject it.
        if isinstance(value, str) and not value.strip():
            return _INSECURE_DEFAULT_KEY
        return value

    @model_validator(mode="after")
    def _require_real_secret_in_production(self):
        if self.ENVIRONMENT.lower() == "production":
            if self.SECRET_KEY == _INSECURE_DEFAULT_KEY:
                raise ValueError("SECRET_KEY must be set to a strong random value in production")
            if len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
        return self

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _no_wildcard_with_credentials(cls, value: str) -> str:
        # Credentials (Authorization header) are allowed, so "*" would let ANY site call the
        # API with a user's token. Require explicit origins.
        if any(o.strip() == "*" for o in value.split(",")):
            raise ValueError("CORS_ORIGINS must list explicit origins, not '*'")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> URL:
        if self.DATABASE_URL:
            raw = self.DATABASE_URL.strip()
            # Accept the common "postgres://" / "postgresql://" spellings and use psycopg 3.
            for prefix in ("postgres://", "postgresql://"):
                if raw.startswith(prefix):
                    raw = "postgresql+psycopg://" + raw[len(prefix):]
            return make_url(raw)

        missing = [
            name
            for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
            if not getattr(self, name)
        ]
        if missing:
            raise RuntimeError(
                "Database is not configured. Set DATABASE_URL, or set "
                f"{', '.join(missing)} in backend/.env (see .env.example)."
            )
        assert self.POSTGRES_PASSWORD is not None
        return URL.create(
            "postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )

    @property
    def safe_database_url(self) -> str:
        """Connection string with the password masked, safe to log."""
        return self.sqlalchemy_url.render_as_string(hide_password=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
