"""FastAPI application factory.

Wires together configuration, logging, middleware, error handling, and routing.
Nothing here holds business logic; it is the composition root.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from fai.api.router import api_router
from fai.core.config import Settings, settings
from fai.core.errors import AppError
from fai.core.logging import configure_logging, get_logger, request_id_var

log = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class InsecureConfigurationError(RuntimeError):
    """Raised when a deployed environment is left on a development default."""


def _assert_production_config(config: Settings) -> None:
    """Refuse to start a production process with development defaults.

    A forgotten secret key is not a warning-level problem: it makes every token
    the service issues forgeable. Failing the boot is the only safe response.
    """
    if not config.is_production:
        return

    problems: list[str] = []
    if "insecure" in config.jwt_secret_key.get_secret_value():
        problems.append("JWT_SECRET_KEY is still the development default")
    if config.debug:
        problems.append("DEBUG is enabled")
    if any(origin == "*" for origin in config.cors_origins):
        problems.append("CORS_ORIGINS contains a wildcard")
    if problems:
        raise InsecureConfigurationError("Refusing to start in production: " + "; ".join(problems))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down sequence."""
    configure_logging(json_output=settings.environment != "local")
    _assert_production_config(settings)
    log.info(
        "application_starting",
        environment=settings.environment,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
    )
    yield
    from fai.db.session import async_engine

    await async_engine.dispose()
    log.info("application_stopped")


def create_app() -> FastAPI:
    """Build and return the configured application."""
    app = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        lifespan=lifespan,
        # The interactive docs describe every endpoint including auth flows.
        # Useful in development, needless attack surface in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # An explicit origin allowlist, never a wildcard: credentialed requests
    # with "*" are rejected by browsers anyway, and a wildcard here would be a
    # silent invitation to relax it later.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Assign a correlation id and log one structured line per request."""
        incoming = request.headers.get(REQUEST_ID_HEADER)
        # An inbound id is echoed for tracing but never trusted as-is: it is
        # attacker-controlled and would otherwise pollute the log index.
        request_id = incoming if incoming and len(incoming) <= 64 else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        finally:
            request_id_var.reset(token)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        log.warning("app_error", code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail)}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        """Last resort. The client learns nothing; the log learns everything."""
        log.exception("unhandled_exception", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {"code": "internal_error", "message": "An unexpected error occurred"}
            },
        )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
