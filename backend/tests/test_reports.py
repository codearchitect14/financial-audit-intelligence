"""Report generation and rendering tests.

The property that matters most: every figure in a report comes from stored
data, so a report is correct and complete even when no LLM is available, and
regenerating the prose can never change a number.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, ClassVar

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
    LLMProvider,
    ReportStatus,
    StatementSection,
)
from fai.db.session import sync_session
from fai.llm.base import LLMRequest, LLMResponse
from fai.reporting import renderer
from fai.reporting.builder import _risk_band, build_facts

API = "/api/v1"
CIK = "0000970001"


# ---------------------------------------------------------------------------
# Unit level
# ---------------------------------------------------------------------------
class TestRiskBand:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (None, "not assessed"),
            (0.0, "no findings"),
            (15.0, "low"),
            (50.0, "elevated"),
            (85.0, "high"),
        ],
    )
    def test_bands(self, score: float | None, expected: str) -> None:
        assert _risk_band(score) == expected

    def test_unassessed_is_distinct_from_no_findings(self) -> None:
        """'We have not looked' and 'we looked and found nothing' are very
        different statements to put in front of an auditor."""
        assert _risk_band(None) != _risk_band(0.0)


class TestRendering:
    CONTENT: ClassVar[dict[str, Any]] = {
        "facts": {
            "company": {"name": "Render Test Co", "cik": "0000000001", "sector": "Tech"},
            "period": {
                "fiscal_year": 2022,
                "fiscal_period": "FY",
                "filing_type": "10-K",
                "period_end_date": "2022-12-31",
            },
            "risk": {
                "score": 82.5,
                "band": "high",
                "scored_at": None,
                "basis": "A triage ordering, not a conclusion.",
            },
            "ratios": {"current_ratio": 2.0, "debt_to_equity": None},
            "findings": [
                {
                    "flag_type": "high_accruals",
                    "severity": "high",
                    "status": "open",
                    "detection_method": "ratio_threshold",
                    "description": "Accruals ratio of 30%.",
                    "detail": {},
                    "explanation": None,
                }
            ],
            "counts": {"total_findings": 1, "open_findings": 1, "by_severity": {}},
            "line_items": {"Assets": "1000000"},
        },
        "narrative": [],
        "generated_at": "2026-09-16T00:00:00+00:00",
    }

    def test_renders_html(self) -> None:
        html = renderer.render_html(self.CONTENT, "Test Report")

        assert "<!DOCTYPE html>" in html
        assert "Render Test Co" in html
        assert "82.5" in html

    def test_states_the_caveat_when_narrative_is_absent(self) -> None:
        html = renderer.render_html(self.CONTENT, "Test Report")
        assert "Narrative sections were not generated" in html
        assert "complete and unaffected" in html

    def test_uncomputable_ratios_are_omitted_not_shown_as_zero(self) -> None:
        """A None row printed in a table invites a reader to see missing data
        as a value of zero."""
        html = renderer.render_html(self.CONTENT, "Test Report")
        assert "current ratio" in html
        assert "debt to equity" not in html

    def test_content_is_escaped(self) -> None:
        """Report text is drawn from filings and model output. Neither is
        trusted markup, and a report gets emailed around."""
        content = {
            **self.CONTENT,
            "facts": {
                **self.CONTENT["facts"],
                "company": {
                    "name": "<script>alert('xss')</script>",
                    "cik": None,
                    "sector": None,
                },
            },
        }
        html = renderer.render_html(content, "Test Report")

        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_footer_disclaims_an_audit_opinion(self) -> None:
        html = renderer.render_html(self.CONTENT, "Test Report")
        # Whitespace-normalised: the template wraps this sentence across lines.
        assert "does not constitute an audit opinion" in " ".join(html.split())

    def test_pdf_availability_is_reported_honestly(self) -> None:
        """The frontend reads this to decide whether to offer a PDF button, so
        it must never claim a capability the host lacks."""
        assert isinstance(renderer.pdf_available(), bool)

    def test_pdf_render_fails_loudly_when_unavailable(self) -> None:
        if renderer.pdf_available():
            pytest.skip("WeasyPrint is available on this host")

        from pathlib import Path

        with pytest.raises(RuntimeError, match="PDF export is unavailable"):
            renderer.render_pdf(self.CONTENT, "Test", Path("unused.pdf"))


# ---------------------------------------------------------------------------
# Integration level
# ---------------------------------------------------------------------------
class StubLLM:
    """An LLM client that returns fixed narrative without a network call."""

    def __init__(self, *, available: bool = True, fail: bool = False):
        self._available = available
        self._fail = fail
        self.calls = 0

    @property
    def available(self) -> bool:
        return self._available

    async def generate(self, db, request: LLMRequest, *, organization_id=None):
        self.calls += 1
        if self._fail:
            raise RuntimeError("provider exploded")
        return LLMResponse(
            content={"heading": "Generated Heading", "body": "Generated narrative body."},
            raw="{}",
            provider=LLMProvider.GROQ,
            model="stub",
        )

    async def budget(self, db):
        from fai.llm.client import BudgetStatus

        return BudgetStatus(calls_today=0, ceiling=900)


@pytest.mark.integration
class TestReportGeneration:
    @pytest.fixture(autouse=True)
    def _purge(self, require_database: None):
        def purge() -> None:
            with sync_session() as session:
                for company in session.execute(select(Company).where(Company.cik == CIK)).scalars():
                    session.delete(company)
                for org in session.execute(
                    select(Organization).where(Organization.name.like("ReportTest%"))
                ).scalars():
                    session.delete(org)
                session.execute(delete(User).where(User.email.like("report-%@example.com")))

        purge()
        yield
        purge()

    @pytest.fixture
    def statement_id(self) -> uuid.UUID:
        with sync_session() as session:
            company = Company(organization_id=None, name="REPORT TEST CO", cik=CIK)
            session.add(company)
            session.flush()

            statement = FinancialStatement(
                organization_id=None,
                company_id=company.id,
                fiscal_year=2022,
                fiscal_period=FiscalPeriod.FY,
                filing_type=FilingType.ANNUAL_10K,
                source_dataset="test",
                source_accession=f"rpt-{uuid.uuid4().hex[:10]}",
                risk_score=76.0,
            )
            session.add(statement)
            session.flush()

            session.add_all(
                [
                    FinancialLineItem(
                        statement_id=statement.id,
                        tag=tag,
                        value=Decimal(value),
                        unit="USD",
                        statement_section=StatementSection.BALANCE_SHEET,
                    )
                    for tag, value in [
                        ("Assets", "1000000"),
                        ("AssetsCurrent", "400000"),
                        ("LiabilitiesCurrent", "200000"),
                    ]
                ]
            )
            session.add(
                AuditFlag(
                    statement_id=statement.id,
                    flag_type="high_accruals",
                    severity=FlagSeverity.HIGH,
                    status=FlagStatus.OPEN,
                    detection_method=DetectionMethod.RATIO_THRESHOLD,
                    description="Accruals ratio of 30% of assets.",
                    detail={"observed": 0.3},
                )
            )
            return statement.id

    async def _register(self, client: httpx.AsyncClient) -> dict:
        response = await client.post(
            f"{API}/auth/register",
            json={
                "email": f"report-{uuid.uuid4().hex[:12]}@example.com",
                "password": "a-sufficiently-long-password",
                "full_name": "Report Test User",
                "organization_name": f"ReportTest {uuid.uuid4().hex[:8]}",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    def _auth(self, body: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {body['tokens']['access_token']}"}

    @pytest.fixture
    def stub_llm(self, app):
        from fai.api.v1.insights import get_llm_client

        stub = StubLLM()
        app.dependency_overrides[get_llm_client] = lambda: stub
        yield stub
        app.dependency_overrides.pop(get_llm_client, None)

    async def test_generates_a_report_with_narrative(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, stub_llm: StubLLM
    ) -> None:
        body = await self._register(client)
        response = await client.post(
            f"{API}/reports",
            json={"statement_id": str(statement_id)},
            headers=self._auth(body),
        )

        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["status"] == ReportStatus.COMPLETE.value
        assert payload["narrative_available"] is True
        assert stub_llm.calls == 3

    async def test_figures_come_from_stored_data_not_the_model(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, stub_llm: StubLLM
    ) -> None:
        """The model writes prose. Every number is computed, which is what makes
        a report checkable against the data."""
        body = await self._register(client)
        response = await client.post(
            f"{API}/reports",
            json={"statement_id": str(statement_id)},
            headers=self._auth(body),
        )

        facts = response.json()["content"]["facts"]
        assert facts["risk"]["score"] == 76.0
        assert facts["ratios"]["current_ratio"] == pytest.approx(2.0)
        assert facts["line_items"]["Assets"] == "1000000"
        assert facts["counts"]["total_findings"] == 1

    async def test_report_is_complete_without_any_llm(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, app
    ) -> None:
        """A deployment with no API keys must still produce a usable report."""
        from fai.api.v1.insights import get_llm_client

        stub = StubLLM(available=False)
        app.dependency_overrides[get_llm_client] = lambda: stub
        try:
            body = await self._register(client)
            response = await client.post(
                f"{API}/reports",
                json={"statement_id": str(statement_id)},
                headers=self._auth(body),
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 201
        payload = response.json()
        assert payload["narrative_available"] is False
        # Every figure is still there.
        assert payload["content"]["facts"]["risk"]["score"] == 76.0
        assert payload["content"]["facts"]["counts"]["total_findings"] == 1
        assert stub.calls == 0

    async def test_narrative_failure_does_not_fail_the_report(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, app
    ) -> None:
        """The figures are the substance; the prose is presentation."""
        from fai.api.v1.insights import get_llm_client

        app.dependency_overrides[get_llm_client] = lambda: StubLLM(fail=True)
        try:
            body = await self._register(client)
            response = await client.post(
                f"{API}/reports",
                json={"statement_id": str(statement_id)},
                headers=self._auth(body),
            )
        finally:
            app.dependency_overrides.pop(get_llm_client, None)

        assert response.status_code == 201
        payload = response.json()
        assert payload["status"] == ReportStatus.COMPLETE.value
        assert payload["narrative_available"] is False
        assert payload["error"]

    async def test_narrative_can_be_skipped_to_save_quota(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, stub_llm: StubLLM
    ) -> None:
        body = await self._register(client)
        response = await client.post(
            f"{API}/reports",
            json={"statement_id": str(statement_id), "include_narrative": False},
            headers=self._auth(body),
        )

        assert response.status_code == 201
        assert stub_llm.calls == 0

    async def test_risk_score_is_snapshotted(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, stub_llm: StubLLM
    ) -> None:
        """A report that has been read and acted on must not change when the
        detectors are later retuned."""
        body = await self._register(client)
        report = (
            await client.post(
                f"{API}/reports",
                json={"statement_id": str(statement_id)},
                headers=self._auth(body),
            )
        ).json()

        with sync_session() as session:
            statement = session.get(FinancialStatement, statement_id)
            assert statement is not None
            statement.risk_score = 12.0

        fetched = await client.get(f"{API}/reports/{report['id']}", headers=self._auth(body))
        assert fetched.json()["risk_score"] == 76.0

    async def test_html_export(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, stub_llm: StubLLM
    ) -> None:
        body = await self._register(client)
        report = (
            await client.post(
                f"{API}/reports",
                json={"statement_id": str(statement_id)},
                headers=self._auth(body),
            )
        ).json()

        response = await client.get(
            f"{API}/reports/{report['id']}/export",
            params={"fmt": "html"},
            headers=self._auth(body),
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "REPORT TEST CO" in response.text

    async def test_export_formats_are_advertised_honestly(self, client: httpx.AsyncClient) -> None:
        body = await self._register(client)
        response = await client.get(f"{API}/reports/formats", headers=self._auth(body))

        payload = response.json()
        assert payload["html"] is True
        assert isinstance(payload["pdf"], bool)
        if not payload["pdf"]:
            assert payload["pdf_unavailable_reason"]

    async def test_pdf_export_is_refused_cleanly_when_unavailable(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, stub_llm: StubLLM
    ) -> None:
        if renderer.pdf_available():
            pytest.skip("WeasyPrint is available on this host")

        body = await self._register(client)
        report = (
            await client.post(
                f"{API}/reports",
                json={"statement_id": str(statement_id)},
                headers=self._auth(body),
            )
        ).json()

        response = await client.get(
            f"{API}/reports/{report['id']}/export",
            params={"fmt": "pdf"},
            headers=self._auth(body),
        )

        assert response.status_code == 422
        assert "HTML instead" in response.json()["error"]["message"]

    async def test_reports_do_not_cross_tenants(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, stub_llm: StubLLM
    ) -> None:
        owner = await self._register(client)
        outsider = await self._register(client)

        report = (
            await client.post(
                f"{API}/reports",
                json={"statement_id": str(statement_id)},
                headers=self._auth(owner),
            )
        ).json()

        assert (
            await client.get(f"{API}/reports/{report['id']}", headers=self._auth(owner))
        ).status_code == 200
        assert (
            await client.get(f"{API}/reports/{report['id']}", headers=self._auth(outsider))
        ).status_code == 404

    async def test_viewer_cannot_generate_a_report(
        self, client: httpx.AsyncClient, statement_id: uuid.UUID, stub_llm: StubLLM
    ) -> None:
        from fai.core.security import create_access_token
        from fai.db.models import UserRole

        body = await self._register(client)
        token = create_access_token(
            user_id=uuid.UUID(body["user"]["id"]),
            organization_id=uuid.UUID(body["organization"]["id"]),
            role=UserRole.VIEWER.value,
        )
        with sync_session() as session:
            user = session.get(User, uuid.UUID(body["user"]["id"]))
            assert user is not None
            user.role = UserRole.VIEWER

        response = await client.post(
            f"{API}/reports",
            json={"statement_id": str(statement_id)},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_unknown_statement_is_not_found(
        self, client: httpx.AsyncClient, stub_llm: StubLLM
    ) -> None:
        body = await self._register(client)
        response = await client.post(
            f"{API}/reports",
            json={"statement_id": str(uuid.uuid4())},
            headers=self._auth(body),
        )
        assert response.status_code == 404


@pytest.mark.integration
class TestBuildFacts:
    def test_findings_are_ordered_by_severity(self) -> None:
        """A reader scans from the top; burying a critical finding under three
        informational ones defeats the point of the report."""
        from fai.db.models.enums import FlagSeverity as S

        class FakeFlag:
            def __init__(self, severity, flag_type):
                self.severity = severity
                self.flag_type = flag_type
                self.status = FlagStatus.OPEN
                self.detection_method = DetectionMethod.RATIO_THRESHOLD
                self.description = flag_type
                self.detail = {}
                self.explanation = None

        class FakeStatement:
            company = None
            fiscal_year = 2022
            fiscal_period = FiscalPeriod.FY
            filing_type = FilingType.ANNUAL_10K
            period_end_date = None
            risk_score = 50.0
            risk_scored_at = None
            line_items: ClassVar[list] = []
            flags: ClassVar[list] = [
                FakeFlag(S.LOW, "low_one"),
                FakeFlag(S.CRITICAL, "critical_one"),
                FakeFlag(S.MEDIUM, "medium_one"),
            ]

        facts = build_facts(FakeStatement())  # type: ignore[arg-type]
        assert [f["severity"] for f in facts["findings"]] == ["critical", "medium", "low"]

    def test_risk_basis_travels_with_the_data(self) -> None:
        """Stated in the payload, not only in the template, so it survives any
        re-rendering into another format."""

        class FakeStatement:
            company = None
            fiscal_year = 2022
            fiscal_period = FiscalPeriod.FY
            filing_type = FilingType.ANNUAL_10K
            period_end_date = None
            risk_score = 50.0
            risk_scored_at = None
            line_items: ClassVar[list] = []
            flags: ClassVar[list] = []

        facts = build_facts(FakeStatement())  # type: ignore[arg-type]
        assert "not a probability of fraud" in facts["risk"]["basis"]
