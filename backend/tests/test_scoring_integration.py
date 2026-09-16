"""Scoring job integration tests.

The properties that matter operationally: the job is re-runnable, it does not
trample a reviewer's triage decisions, and a statement with no data is not
presented as a statement with no risk.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from fai.db.models import AuditFlag, Company, FinancialLineItem, FinancialStatement
from fai.db.models.enums import (
    FilingType,
    FiscalPeriod,
    FlagStatus,
    StatementSection,
)
from fai.db.session import sync_session
from fai.detection.scoring import score_statements

pytestmark = pytest.mark.integration

CIK = "0000960001"


@pytest.fixture(autouse=True)
def _purge(require_database: None):
    def purge() -> None:
        with sync_session() as session:
            for company in session.execute(select(Company).where(Company.cik == CIK)).scalars():
                session.delete(company)

    purge()
    yield
    purge()


def _seed(values: dict[str, str], *, accession: str | None = None) -> uuid.UUID:
    """Create a statement with the given line items."""
    with sync_session() as session:
        company = session.execute(select(Company).where(Company.cik == CIK)).scalar_one_or_none()
        if company is None:
            company = Company(organization_id=None, name="SCORING TEST CO", cik=CIK)
            session.add(company)
            session.flush()

        statement = FinancialStatement(
            organization_id=None,
            company_id=company.id,
            fiscal_year=2022,
            fiscal_period=FiscalPeriod.FY,
            filing_type=FilingType.ANNUAL_10K,
            source_dataset="test",
            source_accession=accession or f"score-{uuid.uuid4().hex[:10]}",
        )
        session.add(statement)
        session.flush()

        for tag, value in values.items():
            session.add(
                FinancialLineItem(
                    statement_id=statement.id,
                    tag=tag,
                    value=Decimal(value),
                    unit="USD",
                    statement_section=StatementSection.OTHER,
                )
            )
        return statement.id


TROUBLED = {
    "Assets": "1000000",
    "Liabilities": "900000",
    "StockholdersEquity": "50000",  # identity out by 5%
    "AssetsCurrent": "100000",
    "LiabilitiesCurrent": "400000",  # illiquid
    "Revenue": "500000",
    "NetIncome": "200000",
    "OperatingCashFlow": "10000",  # heavy accruals
}

CLEAN = {
    "Assets": "1000000",
    "Liabilities": "600000",
    "StockholdersEquity": "400000",
    "AssetsCurrent": "500000",
    "LiabilitiesCurrent": "250000",
    "Revenue": "800000",
    "NetIncome": "80000",
    "OperatingCashFlow": "75000",
}


class TestScoringJob:
    def test_writes_flags_and_a_risk_score(self) -> None:
        statement_id = _seed(TROUBLED)

        with sync_session() as session:
            result = score_statements(session, statement_ids=[statement_id])

        assert result.statements_scored == 1
        assert result.flags_written >= 3

        with sync_session() as session:
            statement = session.get(FinancialStatement, statement_id)
            assert statement is not None
            assert statement.risk_score is not None
            assert statement.risk_score > 0
            assert statement.risk_scored_at is not None

    def test_clean_statement_scores_zero(self) -> None:
        statement_id = _seed(CLEAN)

        with sync_session() as session:
            score_statements(session, statement_ids=[statement_id])

        with sync_session() as session:
            statement = session.get(FinancialStatement, statement_id)
            assert statement is not None
            assert statement.risk_score == 0.0

    def test_troubled_scores_higher_than_clean(self) -> None:
        troubled_id = _seed(TROUBLED)
        clean_id = _seed(CLEAN)

        with sync_session() as session:
            score_statements(session, statement_ids=[troubled_id, clean_id])

        with sync_session() as session:
            troubled = session.get(FinancialStatement, troubled_id)
            clean = session.get(FinancialStatement, clean_id)
            assert troubled is not None and clean is not None
            assert troubled.risk_score > clean.risk_score

    def test_rerun_is_idempotent(self) -> None:
        """The job is expected to run on a schedule over a growing corpus. A
        second pass must refresh findings, not duplicate them."""
        statement_id = _seed(TROUBLED)

        with sync_session() as session:
            score_statements(session, statement_ids=[statement_id])
        with sync_session() as session:
            flags_after_first = len(
                session.execute(select(AuditFlag).where(AuditFlag.statement_id == statement_id))
                .scalars()
                .all()
            )

        with sync_session() as session:
            score_statements(session, statement_ids=[statement_id])
        with sync_session() as session:
            flags_after_second = len(
                session.execute(select(AuditFlag).where(AuditFlag.statement_id == statement_id))
                .scalars()
                .all()
            )

        assert flags_after_first == flags_after_second

    def test_rerun_preserves_reviewer_triage(self) -> None:
        """A reviewer dismissed a finding. Re-running detection must not
        silently reopen it, or the triage work is lost on every schedule tick."""
        statement_id = _seed(TROUBLED)

        with sync_session() as session:
            score_statements(session, statement_ids=[statement_id])

        with sync_session() as session:
            flag = session.execute(
                select(AuditFlag).where(AuditFlag.statement_id == statement_id).limit(1)
            ).scalar_one()
            flag.status = FlagStatus.DISMISSED
            flag_id = flag.id

        with sync_session() as session:
            score_statements(session, statement_ids=[statement_id])

        with sync_session() as session:
            flag = session.get(AuditFlag, flag_id)
            assert flag is not None
            assert flag.status is FlagStatus.DISMISSED

    def test_statement_without_line_items_is_not_scored(self) -> None:
        """Scoring an empty statement zero would present 'no data' as 'no
        risk', which is the more dangerous of the two readings."""
        statement_id = _seed({})

        with sync_session() as session:
            result = score_statements(session, statement_ids=[statement_id])

        assert result.statements_scored == 0

        with sync_session() as session:
            statement = session.get(FinancialStatement, statement_id)
            assert statement is not None
            assert statement.risk_score is None

    def test_findings_carry_reviewable_evidence(self) -> None:
        statement_id = _seed(TROUBLED)

        with sync_session() as session:
            score_statements(session, statement_ids=[statement_id])

        with sync_session() as session:
            flags = (
                session.execute(select(AuditFlag).where(AuditFlag.statement_id == statement_id))
                .scalars()
                .all()
            )

        assert flags
        for flag in flags:
            assert flag.detail, f"{flag.flag_type} carries no evidence"
            assert flag.description
