"""Rate limiting.

Applied to the endpoints where abuse is cheap and damaging: credential entry,
account creation, and anything that spends LLM quota. Everything else is left
unlimited, because a limit that fires on legitimate traffic is an outage.

The limiter keys on client address. Behind a managed proxy that means the
``X-Forwarded-For`` entry, which a determined attacker can rotate; this is a
speed bump against automated abuse, not an authentication control, and is not
relied on for one.

Storage is in-process by default, so each instance counts independently. With
one free-tier instance that is exact. If the service is ever scaled out, set
``RATE_LIMIT_STORAGE_URI`` to a shared Redis so the limit stays global rather
than multiplying by instance count.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from fai.core.config import settings


def _client_key(request: Request) -> str:
    """Rate-limit key for a request.

    An authenticated caller is keyed by user id so that many people behind one
    corporate NAT do not share, and exhaust, a single bucket. Unauthenticated
    callers fall back to the remote address.
    """
    user = getattr(request.state, "rate_limit_user_id", None)
    if user:
        return f"user:{user}"
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_key,
    storage_uri=settings.rate_limit_storage_uri,
    # Disabled under test so that a suite of login cases does not trip the
    # production limit and start failing for the wrong reason.
    enabled=settings.rate_limit_enabled,
    headers_enabled=True,
)
