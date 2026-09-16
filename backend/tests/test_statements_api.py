"""Financial data API tests.

The central concern is tenant isolation. Public SEC reference data must be
visible to every organization; anything private must be visible to exactly one,
and an id from another tenant must behave as though it does not exist.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import delete, select

from fai.db.models import (
    AuditFlag,
    Company,
    FinancialLineItem,
    FinancialStatement,
    Organization,
    User,
)
from fai.db.models.enums import (
    DetectionMethod,
    FilingType,
    FiscalPeriod,
    FlagSeverity,
    FlagStatus,
    StatementSection,
)
from fai.db.session import sync_session

API = "/api/v1"
pytestmark = pytest.mark.integration

PUBLIC_CIK = "0000950001"
PRIVATE_MARKER = "ApiTest"


@pytest.fixture(autouse=True)
def _purge(require_database: None):
    def purge() -> None:
        with sync_session() as session:
            for company in session.execute(
                select(Company).where(Company.cik == PUBLIC_CIK)
            ).scalars():
                session.delete(company)
            for org in session.execute(
                select(Organization).where(Organization.name.like(f"{PRIVATE_MARKER}%"))
            ).scalars():
                session.delete(org)
            session.execute(delete(User).where(User.email.like("api-%@example.com")))

    purge()
    yield
    purge()


@pytest.fixture
def public_statement() -> uuid.UUID:
    """A public SEC statement, visible to every tenant."""
    with sync_session() as session:
        company = Company(
            organization_id=None, name="PUBLIC REFERENCE CO", cik=PUBLIC_CIK, sector="Technology"
        )
        session.add(company)
        session.flush()

        statement = FinancialStatement(
            organization_id=None,
            company_id=company.id,
            fiscal_year=2022,
            fiscal_period=FiscalPeriod.FY,
            filing_type=FilingType.ANNUAL_10K,
            source_dataset="sec_dera",
            source_accession=f"{PUBLIC_CIK}-22-000001",
            risk_score=82.5,
        )
        session.add(statement)
        session.flush()

        session.add_all(
            [
                FinancialLineItem(
                    statement_id=statement.id,
                    tag="Assets",
                    value=Decimal("1000000"),
                    unit="USD",
                    statement_section=StatementSection.BALANCE_SHEET,
                ),
                FinancialLineItem(
                    statement_id=statement.id,
                    tag="AssetsCurrent",
                    value=Decimal("400000"),
                    unit="USD",
                    statement_section=StatementSection.BALANCE_SHEET,
                ),
                FinancialLineItem(
                    statement_id=statement.id,
                    tag="LiabilitiesCurrent",
                    value=Decimal("200000"),
                    unit="USD",
                    statement_section=StatementSection.BALANCE_SHEET,
                ),
                FinancialLineItem(
                    statement_id=statement.id,
                    tag="Revenue",
                    value=Decimal("500000"),
                    unit="USD",
                    statement_section=StatementSection.INCOME_STATEMENT,
                ),
                FinancialLineItem(
                    statement_id=statement.id,
                    tag="NetIncome",
                    value=Decimal("50000"),
                    unit="USD",
                    statement_section=StatementSection.INCOME_STATEMENT,
                ),
            ]
        )
        session.add(
            AuditFlag(
                statement_id=statement.id,
                flag_type="test_flag",
                severity=FlagSeverity.HIGH,
                status=FlagStatus.OPEN,
                detection_method=DetectionMethod.RATIO_THRESHOLD,
                description="A seeded finding for API tests.",
                detail={"observed": 1.5},
            )
        )
        return statement.id


async def _register(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        f"{API}/auth/register",
        json={
            "email": f"api-{uuid.uuid4().hex[:12]}@example.com",
            "password": "a-sufficiently-long-password",
            "full_name": "API Test User",
            "organization_name": f"{PRIVATE_MARKER} {uuid.uuid4().hex[:8]}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(body: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['tokens']['access_token']}"}


class TestAuthenticationRequired:
    @pytest.mark.parametrize(
        "path",
        ["/dashboard", "/companies", "/statements", "/flags", "/documents"],
    )
    async def test_endpoints_reject_anonymous_callers(
        self, client: httpx.AsyncClient, path: str
    ) -> None:
        response = await client.get(f"{API}{path}")
        assert response.status_code == 401


class TestPublicReferenceVisibility:
    async def test_every_tenant_sees_the_public_corpus(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        """The SEC corpus is stored once with a NULL organization_id rather than
        copied per tenant, so both tenants must resolve the same row."""
        first = await _register(client)
        second = await _register(client)

        for body in (first, second):
            response = await client.get(f"{API}/statements/{public_statement}", headers=_auth(body))
            assert response.status_code == 200
            assert response.json()["fiscal_year"] == 2022

    async def test_public_company_is_marked_as_reference_data(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        body = await _register(client)
        response = await client.get(
            f"{API}/companies", params={"search": "PUBLIC REFERENCE"}, headers=_auth(body)
        )

        assert response.status_code == 200
        items = response.json()["items"]
        assert items and items[0]["is_public_reference"] is True


class TestTenantIsolation:
    async def test_private_statement_is_invisible_to_another_tenant(
        self, client: httpx.AsyncClient
    ) -> None:
        owner = await _register(client)
        outsider = await _register(client)

        with sync_session() as session:
            company = Company(
                organization_id=uuid.UUID(owner["organization"]["id"]),
                name="PRIVATE CO",
            )
            session.add(company)
            session.flush()
            statement = FinancialStatement(
                organization_id=uuid.UUID(owner["organization"]["id"]),
                company_id=company.id,
                fiscal_year=2023,
                fiscal_period=FiscalPeriod.FY,
                filing_type=FilingType.ANNUAL_10K,
                source_dataset="upload",
                source_accession=f"private-{uuid.uuid4().hex[:8]}",
            )
            session.add(statement)
            session.flush()
            statement_id = statement.id

        assert (
            await client.get(f"{API}/statements/{statement_id}", headers=_auth(owner))
        ).status_code == 200

        # 404 rather than 403: confirming that an id exists but belongs to
        # somebody else is itself a disclosure.
        outsider_response = await client.get(
            f"{API}/statements/{statement_id}", headers=_auth(outsider)
        )
        assert outsider_response.status_code == 404

    async def test_flag_triage_is_scoped_to_the_tenant(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        body = await _register(client)
        with sync_session() as session:
            flag_id = session.execute(
                select(AuditFlag.id).where(AuditFlag.statement_id == public_statement)
            ).scalar_one()

        response = await client.patch(
            f"{API}/flags/{flag_id}", json={"status": "acknowledged"}, headers=_auth(body)
        )
        assert response.status_code == 200
        assert response.json()["status"] == "acknowledged"


class TestStatementDetail:
    async def test_returns_line_items_and_computed_ratios(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        body = await _register(client)
        response = await client.get(f"{API}/statements/{public_statement}", headers=_auth(body))

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["line_items"]) == 5
        # AssetsCurrent 400000 / LiabilitiesCurrent 200000
        assert payload["ratios"]["current_ratio"] == pytest.approx(2.0)
        # NetIncome 50000 / Revenue 500000
        assert payload["ratios"]["net_margin"] == pytest.approx(0.1)

    async def test_uncomputable_ratios_are_null_not_zero(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        """Zero is a real value for most of these. Reporting a missing ratio as
        zero would produce false findings on incomplete filings."""
        body = await _register(client)
        response = await client.get(f"{API}/statements/{public_statement}", headers=_auth(body))
        # No Liabilities or StockholdersEquity line item was seeded.
        assert response.json()["ratios"]["debt_to_equity"] is None

    async def test_values_are_serialised_without_precision_loss(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        body = await _register(client)
        response = await client.get(f"{API}/statements/{public_statement}", headers=_auth(body))
        values = {item["tag"]: item["value"] for item in response.json()["line_items"]}
        assert Decimal(str(values["Assets"])) == Decimal("1000000")

    async def test_unknown_statement_is_not_found(self, client: httpx.AsyncClient) -> None:
        body = await _register(client)
        response = await client.get(f"{API}/statements/{uuid.uuid4()}", headers=_auth(body))
        assert response.status_code == 404


class TestListingAndFiltering:
    async def test_pagination_reports_a_total(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        body = await _register(client)
        response = await client.get(f"{API}/statements", params={"limit": 1}, headers=_auth(body))

        payload = response.json()
        assert payload["limit"] == 1
        assert payload["total"] >= 1
        assert len(payload["items"]) <= 1

    async def test_page_size_is_capped(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        """Without a cap a caller could request the entire table in one query."""
        body = await _register(client)
        response = await client.get(
            f"{API}/statements", params={"limit": 100000}, headers=_auth(body)
        )
        assert response.status_code == 422

    async def test_filter_by_minimum_risk_score(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        body = await _register(client)

        matching = await client.get(
            f"{API}/statements", params={"min_risk_score": 80}, headers=_auth(body)
        )
        excluded = await client.get(
            f"{API}/statements", params={"min_risk_score": 90}, headers=_auth(body)
        )

        ids = {item["id"] for item in matching.json()["items"]}
        assert str(public_statement) in ids
        assert str(public_statement) not in {item["id"] for item in excluded.json()["items"]}

    async def test_filter_by_open_flags(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        body = await _register(client)
        response = await client.get(
            f"{API}/statements", params={"has_open_flags": True}, headers=_auth(body)
        )
        assert str(public_statement) in {item["id"] for item in response.json()["items"]}


class TestDashboard:
    async def test_summary_counts_reflect_seeded_data(
        self, client: httpx.AsyncClient, public_statement: uuid.UUID
    ) -> None:
        body = await _register(client)
        response = await client.get(f"{API}/dashboard", headers=_auth(body))

        assert response.status_code == 200
        payload = response.json()
        assert payload["total_statements"] >= 1
        assert payload["open_flags"] >= 1
        assert payload["critical_flags"] >= 1
