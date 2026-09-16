"""Health endpoint and application-wiring tests."""

from __future__ import annotations

import httpx
import pytest

from fai.core.config import Settings
from fai.main import REQUEST_ID_HEADER, InsecureConfigurationError, _assert_production_config


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "ci"


async def test_health_does_not_require_a_database(client: httpx.AsyncClient) -> None:
    """Liveness must not depend on Postgres.

    If it did, a brief database blip would pull every instance out of rotation
    instead of degrading readiness only.
    """
    response = await client.get("/api/v1/health")
    assert response.status_code == 200


async def test_every_response_carries_a_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.headers.get(REQUEST_ID_HEADER)


async def test_inbound_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={REQUEST_ID_HEADER: "client-supplied-id"})
    assert response.headers[REQUEST_ID_HEADER] == "client-supplied-id"


async def test_oversized_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    """A caller must not be able to write an unbounded value into the log index."""
    response = await client.get("/api/v1/health", headers={REQUEST_ID_HEADER: "x" * 500})
    assert response.headers[REQUEST_ID_HEADER] != "x" * 500
    assert len(response.headers[REQUEST_ID_HEADER]) <= 64


async def test_unknown_route_uses_the_shared_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert "error" in response.json()
    assert "code" in response.json()["error"]


class TestProductionConfigGuard:
    """The start-up guard is the only thing standing between a typo in the
    deployment environment and a service issuing forgeable tokens."""

    def test_local_environment_is_never_blocked(self) -> None:
        _assert_production_config(Settings(environment="local", debug=True))

    def test_production_rejects_the_default_secret(self) -> None:
        with pytest.raises(InsecureConfigurationError, match="JWT_SECRET_KEY"):
            _assert_production_config(
                Settings(
                    environment="production",
                    jwt_secret_key="insecure-development-key-change-me",
                )
            )

    def test_production_rejects_debug_mode(self) -> None:
        with pytest.raises(InsecureConfigurationError, match="DEBUG"):
            _assert_production_config(
                Settings(environment="production", debug=True, jwt_secret_key="a-real-secret")
            )

    def test_production_rejects_a_cors_wildcard(self) -> None:
        with pytest.raises(InsecureConfigurationError, match="CORS"):
            _assert_production_config(
                Settings(
                    environment="production",
                    jwt_secret_key="a-real-secret",
                    cors_origins=["*"],
                )
            )

    def test_correctly_configured_production_passes(self) -> None:
        _assert_production_config(
            Settings(
                environment="production",
                debug=False,
                jwt_secret_key="a-real-secret",
                cors_origins=["https://app.example.com"],
            )
        )
