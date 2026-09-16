"""Authentication and authorization tests.

These exercise the real HTTP stack against a real database, because the things
most worth testing here (tenant isolation, token type confusion, refresh
rotation) are properties of the whole request path, not of any one function.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select

from fai.core.errors import AuthenticationError
from fai.core.permissions import can, has_at_least, rank
from fai.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from fai.db.models import Organization, RefreshToken, User, UserRole
from fai.db.session import sync_session

API = "/api/v1"


# ---------------------------------------------------------------------------
# Unit level: no database required
# ---------------------------------------------------------------------------
class TestPasswordHashing:
    def test_hash_is_verifiable(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed)

    def test_wrong_password_is_rejected(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert not verify_password("incorrect horse battery staple", hashed)

    def test_hash_is_salted(self) -> None:
        """Identical passwords must not produce identical hashes, or the hash
        table itself reveals which accounts share a password."""
        assert hash_password("same password") != hash_password("same password")

    def test_uses_argon2(self) -> None:
        assert hash_password("x" * 12).startswith("$argon2")

    def test_malformed_hash_fails_closed(self) -> None:
        """A corrupted row must fail the login, not crash the endpoint."""
        assert verify_password("anything", "not-a-valid-hash") is False

    def test_current_hash_does_not_need_rehashing(self) -> None:
        assert needs_rehash(hash_password("x" * 12)) is False


class TestAccessTokens:
    def _token(self, **kwargs: object) -> str:
        defaults = {
            "user_id": uuid.uuid4(),
            "organization_id": uuid.uuid4(),
            "role": "auditor",
        }
        defaults.update(kwargs)
        return create_access_token(**defaults)  # type: ignore[arg-type]

    def test_round_trips_claims(self) -> None:
        user_id, org_id = uuid.uuid4(), uuid.uuid4()
        claims = decode_access_token(
            create_access_token(user_id=user_id, organization_id=org_id, role="admin")
        )

        assert claims.user_id == user_id
        assert claims.organization_id == org_id
        assert claims.role == "admin"
        assert claims.token_type == "access"

    def test_expired_token_is_rejected(self) -> None:
        token = self._token(expires_delta=timedelta(seconds=-1))
        with pytest.raises(AuthenticationError):
            decode_access_token(token)

    def test_tampered_token_is_rejected(self) -> None:
        token = self._token()
        with pytest.raises(AuthenticationError):
            decode_access_token(token[:-4] + "AAAA")

    def test_unsigned_token_is_rejected(self) -> None:
        """The classic 'alg: none' forgery. Rejected because the decoder pins an
        explicit algorithm list rather than trusting the token's header."""
        import jwt

        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "org": str(uuid.uuid4()),
                "role": "admin",
                "typ": "access",
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            key="",
            algorithm="none",
        )
        with pytest.raises(AuthenticationError):
            decode_access_token(forged)

    def test_token_of_the_wrong_type_is_rejected(self) -> None:
        """Without the typ check a 7-day refresh token would be honoured as a
        30-minute access token."""
        import jwt

        from fai.core.config import settings

        refresh_shaped = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "org": str(uuid.uuid4()),
                "role": "admin",
                "typ": "refresh",
                "exp": int((datetime.now(UTC) + timedelta(days=7)).timestamp()),
            },
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(AuthenticationError):
            decode_access_token(refresh_shaped)

    def test_garbage_is_rejected(self) -> None:
        with pytest.raises(AuthenticationError):
            decode_access_token("not-a-token")


class TestRoleHierarchy:
    def test_ordering(self) -> None:
        assert (
            rank(UserRole.ADMIN)
            > rank(UserRole.AUDITOR)
            > rank(UserRole.REVIEWER)
            > rank(UserRole.VIEWER)
        )

    def test_higher_role_satisfies_lower_requirement(self) -> None:
        assert has_at_least(UserRole.ADMIN, UserRole.VIEWER)

    def test_lower_role_does_not_satisfy_higher_requirement(self) -> None:
        assert not has_at_least(UserRole.VIEWER, UserRole.AUDITOR)

    def test_unknown_role_fails_closed(self) -> None:
        """A corrupted or forward-dated role value must deny, never allow."""
        assert rank("superuser") == -1
        assert not has_at_least("superuser", UserRole.VIEWER)

    def test_capabilities_follow_the_hierarchy(self) -> None:
        assert can(UserRole.VIEWER, "data:read")
        assert not can(UserRole.VIEWER, "reports:generate")
        assert can(UserRole.AUDITOR, "reports:generate")
        assert not can(UserRole.AUDITOR, "users:manage")
        assert can(UserRole.ADMIN, "users:manage")

    def test_unknown_capability_is_denied(self) -> None:
        assert not can(UserRole.ADMIN, "not:a:capability")


# ---------------------------------------------------------------------------
# Integration level: full HTTP stack against a real database
# ---------------------------------------------------------------------------
@pytest.fixture
def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(autouse=True)
def _purge_test_rows(require_database: None):
    """Remove organizations created by this module, before and after."""

    def purge() -> None:
        with sync_session() as session:
            orgs = session.execute(
                select(Organization).where(Organization.name.like("AuthTest%"))
            ).scalars()
            for org in orgs:
                session.delete(org)
            session.execute(delete(User).where(User.email.like("user-%@example.com")))

    purge()
    yield
    purge()


async def _register(
    client: httpx.AsyncClient, email: str, *, password: str = "a-sufficiently-long-password"
) -> dict:
    response = await client.post(
        f"{API}/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Test User",
            "organization_name": f"AuthTest {uuid.uuid4().hex[:8]}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
class TestRegistration:
    async def test_creates_organization_and_admin_user(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)

        assert body["user"]["email"] == unique_email
        # Somebody has to be able to invite the others; an organization with no
        # administrator is unusable.
        assert body["user"]["role"] == UserRole.ADMIN.value
        assert body["organization"]["slug"]
        assert body["tokens"]["access_token"]
        assert body["tokens"]["refresh_token"]

    async def test_email_is_normalised_to_lowercase(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        """The uniqueness index is plain, so without normalisation two casings
        of one address would both register."""
        body = await _register(client, unique_email.upper())
        assert body["user"]["email"] == unique_email.lower()

    async def test_duplicate_email_is_rejected(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        await _register(client, unique_email)
        response = await client.post(
            f"{API}/auth/register",
            json={
                "email": unique_email,
                "password": "another-long-enough-password",
                "full_name": "Second User",
                "organization_name": "AuthTest Duplicate",
            },
        )
        assert response.status_code == 409

    async def test_short_password_is_rejected(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        response = await client.post(
            f"{API}/auth/register",
            json={
                "email": unique_email,
                "password": "short",
                "full_name": "Test User",
                "organization_name": "AuthTest Short",
            },
        )
        assert response.status_code == 422

    async def test_password_is_never_echoed(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        password = "a-very-distinctive-password-value"
        body = await _register(client, unique_email, password=password)
        assert password not in str(body)

    async def test_password_is_stored_hashed(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        password = "a-sufficiently-long-password"
        await _register(client, unique_email, password=password)

        with sync_session() as session:
            stored = session.execute(
                select(User.hashed_password).where(User.email == unique_email)
            ).scalar_one()

        assert stored != password
        assert stored.startswith("$argon2")


@pytest.mark.integration
class TestLogin:
    async def test_valid_credentials_return_tokens(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        await _register(client, unique_email)
        response = await client.post(
            f"{API}/auth/login",
            json={"email": unique_email, "password": "a-sufficiently-long-password"},
        )

        assert response.status_code == 200
        assert response.json()["access_token"]
        assert response.json()["token_type"] == "bearer"

    async def test_wrong_password_is_rejected(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        await _register(client, unique_email)
        response = await client.post(
            f"{API}/auth/login",
            json={"email": unique_email, "password": "the-wrong-password-entirely"},
        )
        assert response.status_code == 401

    async def test_unknown_and_wrong_password_are_indistinguishable(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        """Different messages would hand an attacker a list of valid accounts."""
        await _register(client, unique_email)

        wrong_password = await client.post(
            f"{API}/auth/login",
            json={"email": unique_email, "password": "the-wrong-password-entirely"},
        )
        unknown_user = await client.post(
            f"{API}/auth/login",
            json={"email": "nobody-here@example.com", "password": "the-wrong-password-entirely"},
        )

        assert wrong_password.status_code == unknown_user.status_code == 401
        assert wrong_password.json() == unknown_user.json()

    async def test_deactivated_user_cannot_log_in(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        await _register(client, unique_email)
        with sync_session() as session:
            user = session.execute(select(User).where(User.email == unique_email)).scalar_one()
            user.is_active = False

        response = await client.post(
            f"{API}/auth/login",
            json={"email": unique_email, "password": "a-sufficiently-long-password"},
        )
        assert response.status_code == 401

    async def test_failed_login_is_recorded_without_the_password(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        from fai.db.models import ActivityLog

        await _register(client, unique_email)
        await client.post(
            f"{API}/auth/login",
            json={"email": unique_email, "password": "a-distinctive-wrong-password"},
        )

        with sync_session() as session:
            rows = (
                session.execute(
                    select(ActivityLog).where(ActivityLog.action == "user.login_failed")
                )
                .scalars()
                .all()
            )

        assert rows
        assert not any("a-distinctive-wrong-password" in str(row.detail) for row in rows)


@pytest.mark.integration
class TestCurrentUser:
    async def test_me_returns_the_authenticated_user(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)
        response = await client.get(f"{API}/auth/me", headers=_auth(body["tokens"]["access_token"]))

        assert response.status_code == 200
        assert response.json()["email"] == unique_email

    async def test_missing_token_is_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"{API}/auth/me")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"

    async def test_garbage_token_is_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"{API}/auth/me", headers=_auth("not-a-token"))
        assert response.status_code == 401

    async def test_token_for_a_deleted_user_is_rejected(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)
        token = body["tokens"]["access_token"]

        with sync_session() as session:
            user = session.execute(select(User).where(User.email == unique_email)).scalar_one()
            session.delete(user)

        response = await client.get(f"{API}/auth/me", headers=_auth(token))
        assert response.status_code == 401

    async def test_deactivation_takes_effect_immediately(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        """The user is loaded on every request precisely so that deactivating
        an account does not wait for the current access token to expire."""
        body = await _register(client, unique_email)
        token = body["tokens"]["access_token"]

        assert (await client.get(f"{API}/auth/me", headers=_auth(token))).status_code == 200

        with sync_session() as session:
            user = session.execute(select(User).where(User.email == unique_email)).scalar_one()
            user.is_active = False

        assert (await client.get(f"{API}/auth/me", headers=_auth(token))).status_code == 401


@pytest.mark.integration
class TestRefreshRotation:
    async def test_refresh_returns_a_new_pair(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)
        original = body["tokens"]["refresh_token"]

        response = await client.post(f"{API}/auth/refresh", json={"refresh_token": original})

        assert response.status_code == 200
        assert response.json()["refresh_token"] != original

    async def test_old_token_stops_working_after_rotation(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)
        original = body["tokens"]["refresh_token"]

        await client.post(f"{API}/auth/refresh", json={"refresh_token": original})
        replay = await client.post(f"{API}/auth/refresh", json={"refresh_token": original})

        assert replay.status_code == 401

    async def test_reuse_revokes_the_whole_session_family(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        """A rotated token presented again means somebody has a stolen copy.
        Re-issuing would let the thief keep the session alive indefinitely."""
        body = await _register(client, unique_email)
        original = body["tokens"]["refresh_token"]

        rotated = (
            await client.post(f"{API}/auth/refresh", json={"refresh_token": original})
        ).json()["refresh_token"]

        # The thief replays the old token.
        await client.post(f"{API}/auth/refresh", json={"refresh_token": original})

        # The legitimate client's current token is now dead too.
        response = await client.post(f"{API}/auth/refresh", json={"refresh_token": rotated})
        assert response.status_code == 401

    async def test_unknown_refresh_token_is_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            f"{API}/auth/refresh", json={"refresh_token": "nonexistent-token-value"}
        )
        assert response.status_code == 401

    async def test_expired_refresh_token_is_rejected(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)
        original = body["tokens"]["refresh_token"]

        with sync_session() as session:
            record = session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(original))
            ).scalar_one()
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

        response = await client.post(f"{API}/auth/refresh", json={"refresh_token": original})
        assert response.status_code == 401

    async def test_only_the_hash_is_stored(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        """A database disclosure must not hand out usable sessions."""
        body = await _register(client, unique_email)
        original = body["tokens"]["refresh_token"]

        with sync_session() as session:
            hashes = session.execute(select(RefreshToken.token_hash)).scalars().all()

        assert original not in hashes
        assert hash_token(original) in hashes


@pytest.mark.integration
class TestLogout:
    async def test_logout_revokes_the_session(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)
        tokens = body["tokens"]

        response = await client.post(
            f"{API}/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
            headers=_auth(tokens["access_token"]),
        )
        assert response.status_code == 204

        replay = await client.post(
            f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert replay.status_code == 401

    async def test_logout_is_idempotent(self, client: httpx.AsyncClient, unique_email: str) -> None:
        body = await _register(client, unique_email)
        tokens = body["tokens"]
        headers = _auth(tokens["access_token"])

        first = await client.post(
            f"{API}/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
        )
        second = await client.post(
            f"{API}/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
        )
        assert first.status_code == second.status_code == 204


@pytest.mark.integration
class TestRoleManagement:
    async def test_admin_can_change_a_members_role(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)
        admin_token = body["tokens"]["access_token"]
        org_id = uuid.UUID(body["organization"]["id"])

        with sync_session() as session:
            member = User(
                organization_id=org_id,
                email=f"member-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password=hash_password("a-sufficiently-long-password"),
                full_name="Member",
                role=UserRole.VIEWER,
            )
            session.add(member)
            session.flush()
            member_id = member.id

        response = await client.patch(
            f"{API}/auth/users/{member_id}/role",
            json={"role": "auditor"},
            headers=_auth(admin_token),
        )

        assert response.status_code == 200
        assert response.json()["role"] == "auditor"

    async def test_non_admin_cannot_change_roles(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)
        org_id = uuid.UUID(body["organization"]["id"])
        user_id = uuid.UUID(body["user"]["id"])

        with sync_session() as session:
            user = session.execute(select(User).where(User.id == user_id)).scalar_one()
            user.role = UserRole.AUDITOR

        token = create_access_token(
            user_id=user_id, organization_id=org_id, role=UserRole.AUDITOR.value
        )
        response = await client.patch(
            f"{API}/auth/users/{user_id}/role",
            json={"role": "admin"},
            headers=_auth(token),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "permission_denied"

    async def test_admin_cannot_demote_themselves(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        """Otherwise an organization can end up with no administrator and no way
        to create one."""
        body = await _register(client, unique_email)

        response = await client.patch(
            f"{API}/auth/users/{body['user']['id']}/role",
            json={"role": "viewer"},
            headers=_auth(body["tokens"]["access_token"]),
        )
        assert response.status_code == 409

    async def test_admin_cannot_touch_another_organizations_member(
        self, client: httpx.AsyncClient
    ) -> None:
        """The core tenant-isolation property: a valid id from another tenant
        must not resolve."""
        first = await _register(client, f"user-{uuid.uuid4().hex[:12]}@example.com")
        second = await _register(client, f"user-{uuid.uuid4().hex[:12]}@example.com")

        response = await client.patch(
            f"{API}/auth/users/{second['user']['id']}/role",
            json={"role": "viewer"},
            headers=_auth(first["tokens"]["access_token"]),
        )

        assert response.status_code == 404

    async def test_malformed_user_id_is_rejected(
        self, client: httpx.AsyncClient, unique_email: str
    ) -> None:
        body = await _register(client, unique_email)
        response = await client.patch(
            f"{API}/auth/users/not-a-uuid/role",
            json={"role": "viewer"},
            headers=_auth(body["tokens"]["access_token"]),
        )
        assert response.status_code == 422
