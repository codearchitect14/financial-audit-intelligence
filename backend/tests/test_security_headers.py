"""Security header tests.

Headers are trivially easy to remove by accident during a refactor and give no
visible symptom when they are gone. These assert the ones that actually change
browser behaviour.
"""

from __future__ import annotations

import httpx
import pytest

from fai.core.config import Settings
from fai.main import create_app

API = "/api/v1"


class TestSecurityHeaders:
    async def test_content_type_is_not_sniffed(self, client: httpx.AsyncClient) -> None:
        """Sniffing is how a text/plain upload gets executed as script."""
        response = await client.get(f"{API}/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    async def test_framing_is_denied(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"{API}/health")
        assert response.headers["X-Frame-Options"] == "DENY"

    async def test_referrer_is_not_leaked(self, client: httpx.AsyncClient) -> None:
        # A URL here can contain a statement or report id.
        response = await client.get(f"{API}/health")
        assert response.headers["Referrer-Policy"] == "no-referrer"

    async def test_csp_forbids_script_and_framing(self, client: httpx.AsyncClient) -> None:
        """An exported report is the only HTML this service returns, and it
        needs no script, no framing, and no outbound connections."""
        response = await client.get(f"{API}/health")
        csp = response.headers["Content-Security-Policy"]

        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "script-src" not in csp or "script-src 'none'" in csp

    async def test_headers_are_present_on_errors_too(self, client: httpx.AsyncClient) -> None:
        # An error response is still a response a browser may render.
        response = await client.get(f"{API}/does-not-exist")

        assert response.status_code == 404
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    async def test_hsts_is_absent_outside_production(self, client: httpx.AsyncClient) -> None:
        """Sending HSTS from a local http server pins the browser to https for
        localhost and breaks development for everyone on that machine."""
        response = await client.get(f"{API}/health")
        assert "Strict-Transport-Security" not in response.headers

    async def test_hsts_is_present_in_production(self) -> None:
        production = create_app()
        # The guard reads settings at request time, so the app is exercised
        # with a production settings object rather than a rebuilt module.
        import fai.main as main_module

        original = main_module.settings
        main_module.settings = Settings(
            environment="production",
            debug=False,
            jwt_secret_key="a-real-production-secret",
            cors_origins=["https://app.example.com"],
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=production),
                base_url="http://testserver",
            ) as client:
                response = await client.get(f"{API}/health")
            assert "Strict-Transport-Security" in response.headers
        finally:
            main_module.settings = original


class TestDocsExposure:
    async def test_interactive_docs_are_available_outside_production(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/docs")
        assert response.status_code == 200

    def test_docs_are_disabled_in_production(self) -> None:
        """The schema describes every endpoint including the auth flows. Useful
        in development, needless attack surface in production."""
        import fai.main as main_module

        original = main_module.settings
        main_module.settings = Settings(
            environment="production",
            debug=False,
            jwt_secret_key="a-real-production-secret",
            cors_origins=["https://app.example.com"],
        )
        try:
            production = create_app()
            assert production.docs_url is None
            assert production.openapi_url is None
            assert production.redoc_url is None
        finally:
            main_module.settings = original


class TestCors:
    async def test_configured_origin_is_allowed(self, client: httpx.AsyncClient) -> None:
        response = await client.options(
            f"{API}/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"

    async def test_unknown_origin_is_not_allowed(self, client: httpx.AsyncClient) -> None:
        response = await client.options(
            f"{API}/health",
            headers={
                "Origin": "https://attacker.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") != (
            "https://attacker.example.com"
        )

    async def test_no_wildcard_origin_is_ever_returned(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"{API}/health", headers={"Origin": "http://localhost:5173"})
        assert response.headers.get("access-control-allow-origin") != "*"


@pytest.mark.parametrize(
    "path",
    ["/api/v1/health", "/api/v1/health/ready", "/docs"],
)
async def test_no_server_version_is_advertised(client: httpx.AsyncClient, path: str) -> None:
    """A precise server version turns a published CVE into a targeted attack."""
    response = await client.get(path)
    server = response.headers.get("server", "")
    assert "/" not in server, f"{path} advertises a version: {server!r}"
