"""Application configuration.

All runtime configuration is read from the environment (or a local ``.env``
file) exactly once, at import time, into a frozen settings object. Nothing in
the codebase may read ``os.environ`` directly; that keeps every knob
discoverable in one place and lets the test suite override values cleanly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]


class Settings(BaseSettings):
    """Typed view over the process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    environment: Environment = "local"
    debug: bool = False
    project_name: str = "Financial Audit Intelligence"
    api_v1_prefix: str = "/api/v1"

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    # Single source of truth. The async and sync DSNs are derived from it so
    # that a deployment only ever has to set one connection string.
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql://fai:fai@localhost:5432/fai"),
        description="Postgres DSN without a driver suffix.",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("insecure-development-key-change-me"),
        description="HMAC signing key for access and refresh tokens.",
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    # NoDecode: pydantic-settings would otherwise try to JSON-decode this in
    # the env source, before any validator runs, so a plain comma-separated
    # value would fail to load. The validator below handles both forms.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    # Disabled in the test suite so that a suite of login cases does not
    # trip the production limit and fail for the wrong reason.
    rate_limit_enabled: bool = True
    # In-process by default, which is exact for a single instance. Point at
    # a shared Redis before scaling out, or the effective limit multiplies
    # by the instance count.
    rate_limit_storage_uri: str = "memory://"

    # ------------------------------------------------------------------
    # LLM providers (Phase 5)
    # ------------------------------------------------------------------
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-20b"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_fallback_model: str = "gemini-2.5-flash"
    llm_daily_call_budget: int = 900

    # ------------------------------------------------------------------
    # Embeddings (Phase 4)
    # ------------------------------------------------------------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Must match the vector(N) column width in the database. Changing this
    # requires a migration, so it is asserted against the model at startup.
    embedding_dimensions: int = 384

    # ------------------------------------------------------------------
    # Ingestion (Phase 1)
    # ------------------------------------------------------------------
    # The SEC rejects unidentified clients. This header is mandatory and must
    # carry a real contact address. See docs/data-pipeline.md.
    sec_user_agent: str = "FinancialAuditIntelligence contact@example.com"
    sec_requests_per_second: float = 8.0
    data_dir: str = "./data"

    # ------------------------------------------------------------------
    # Uploads
    # ------------------------------------------------------------------
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_upload_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["application/pdf", "text/plain", "text/csv"]
    )

    @field_validator("cors_origins", "allowed_upload_types", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept either a comma-separated string or a JSON list."""
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                import json

                return json.loads(raw)
            return [item.strip() for item in raw.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def async_database_url(self) -> str:
        """DSN for the FastAPI request path (asyncpg driver)."""
        return str(self.database_url).replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def sync_database_url(self) -> str:
        """DSN for Alembic and batch scripts (psycopg 3 driver)."""
        return str(self.database_url).replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


settings = get_settings()
