"""Rate limiting tests.

These run with the limiter **enabled**, unlike the rest of the suite.

That distinction matters. The rest of the suite disables rate limiting so a
dozen login cases do not trip a production limit and fail for the wrong reason,
but that also meant no test ever exercised the decorated code path. A real
defect hid there: slowapi's ``headers_enabled`` requires every decorated
endpoint to declare a ``response: Response`` parameter, and without one it
raises on success, turning every rate-limited endpoint into a 500. The bug was
found by running the service by hand, not by the suite.

This module exists so that cannot happen again.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from fai.core.rate_limit import limiter

API = "/api/v1"

# Endpoints carrying a @limiter.limit decorator. Each must be reachable without
# raising, which is the property the original defect broke.
RATE_LIMITED_ENDPOINTS = [
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/documents"),
    ("GET", "/search"),
    ("POST", "/explain"),
    ("POST", "/ask"),
    ("POST", "/reports"),
]


@pytest.fixture
def limited_app(app: FastAPI):
    """Enable the limiter for this module only, then restore it."""
    previous = limiter.enabled
    limiter.enabled = True
    # Counters persist in the limiter's in-process store across tests, so they
    # are reset to keep each case independent.
    limiter.reset()
    yield app
    limiter.enabled = previous
    limiter.reset()


@pytest.fixture
async def limited_client(limited_app: FastAPI):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limited_app),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.integration
class TestRateLimitedEndpointsDoNotError:
    """The regression guard.

    A rate-limited endpoint must return its own status code, never a 500 from
    the limiter trying to attach headers to a response that does not exist.
    """

    async def test_register_succeeds_with_the_limiter_enabled(
        self, limited_client: httpx.AsyncClient, require_database: None
    ) -> None:
        response = await limited_client.post(
            f"{API}/auth/register",
            json={
                "email": f"rl-{uuid.uuid4().hex[:12]}@example.com",
                "password": "a-sufficiently-long-password",
                "full_name": "Rate Limit Test",
                "organization_name": f"RateLimitTest {uuid.uuid4().hex[:8]}",
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["error"] if response.status_code >= 400 else True

    async def test_login_failure_returns_401_not_500(
        self, limited_client: httpx.AsyncClient, require_database: None
    ) -> None:
        response = await limited_client.post(
            f"{API}/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password-entirely"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"

    async def test_refresh_with_a_bad_token_returns_401_not_500(
        self, limited_client: httpx.AsyncClient, require_database: None
    ) -> None:
        response = await limited_client.post(
            f"{API}/auth/refresh", json={"refresh_token": "not-a-real-token"}
        )
        assert response.status_code == 401

    async def test_search_returns_401_not_500_when_unauthenticated(
        self, limited_client: httpx.AsyncClient
    ) -> None:
        response = await limited_client.get(f"{API}/search", params={"q": "revenue"})
        assert response.status_code == 401

    @pytest.mark.parametrize(("method", "path"), RATE_LIMITED_ENDPOINTS)
    async def test_no_rate_limited_endpoint_returns_a_server_error(
        self, limited_client: httpx.AsyncClient, method: str, path: str
    ) -> None:
        """Unauthenticated, so most return 401 or 422. None may return 5xx."""
        response = await limited_client.request(
            method, f"{API}{path}", json={} if method == "POST" else None
        )
        assert response.status_code < 500, (
            f"{method} {path} returned {response.status_code}: {response.text[:200]}"
        )


@pytest.mark.integration
class TestRateLimitEnforcement:
    async def test_login_is_limited_after_repeated_attempts(
        self, limited_client: httpx.AsyncClient, require_database: None
    ) -> None:
        """The limit exists to make online password guessing impractical."""
        payload = {"email": "nobody@example.com", "password": "wrong-password"}

        statuses = []
        # The configured limit is 10/minute; 12 attempts must cross it.
        for _ in range(12):
            response = await limited_client.post(f"{API}/auth/login", json=payload)
            statuses.append(response.status_code)

        assert 429 in statuses, f"never rate limited, saw {sorted(set(statuses))}"

    async def test_limit_response_uses_the_shared_error_envelope(
        self, limited_client: httpx.AsyncClient, require_database: None
    ) -> None:
        payload = {"email": "nobody@example.com", "password": "wrong-password"}

        limited = None
        for _ in range(15):
            response = await limited_client.post(f"{API}/auth/login", json=payload)
            if response.status_code == 429:
                limited = response
                break

        assert limited is not None, "expected to hit the limit"
        body = limited.json()
        assert body["error"]["code"] == "rate_limited"
        assert "message" in body["error"]

    async def test_rate_limit_headers_are_present_on_a_successful_call(
        self, limited_client: httpx.AsyncClient, require_database: None
    ) -> None:
        """Headers are the reason the Response parameter is required at all.

        They are injected into the Response object the endpoint declares, so
        they appear only on a response the endpoint actually returns. An
        endpoint that raises (a 401, say) is rendered by the exception handler
        instead, which builds a fresh response and carries no limiter headers.

        If these stop appearing, someone has turned headers_enabled off and the
        Response parameters on every decorated endpoint have become dead weight.
        """
        response = await limited_client.post(
            f"{API}/auth/register",
            json={
                "email": f"rl-{uuid.uuid4().hex[:12]}@example.com",
                "password": "a-sufficiently-long-password",
                "full_name": "Header Test",
                "organization_name": f"RateLimitTest {uuid.uuid4().hex[:8]}",
            },
        )

        assert response.status_code == 201, response.text
        header_names = {name.lower() for name in response.headers}
        assert any(name.startswith("x-ratelimit") for name in header_names), (
            f"no rate limit headers in {sorted(header_names)}"
        )
