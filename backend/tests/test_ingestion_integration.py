"""Loader integration tests.

The property that matters most here is idempotency. Ingestion runs over
multi-hundred-megabyte archives, is expected to be interrupted, and is routinely
re-run over an overlapping quarter. A second run must converge to the same
state, not duplicate rows or fail on a constraint.
"""

from __future__ import annotations

import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from fai.db.models import Company, FinancialLineItem, FinancialStatement
from fai.db.session import sync_session
from fai.ingestion.aaer import load_aaer_mapping
from fai.ingestion.pipeline import ingest_archive

pytestmark = pytest.mark.integration

SUB_HEADER = "adsh\tcik\tname\tsic\tcountryba\tform\tfy\tfp\tperiod\tfiled"
NUM_HEADER = "adsh\ttag\tddate\tqtrs\tuom\tvalue"

ACCESSION = "0000900001-23-000001"
CIK = "0000900001"


@pytest.fixture(autouse=True)
def _db(require_database: None) -> None:
    """Skip this module unless a database is available."""


@pytest.fixture(autouse=True)
def _clean() -> None:
    """Remove rows this module creates, before and after, so runs are isolated."""

    def purge() -> None:
        with sync_session() as session:
            company = session.execute(
                select(Company).where(Company.cik == CIK)
            ).scalar_one_or_none()
            if company is not None:
                session.delete(company)

    purge()
    yield
    purge()


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    path = tmp_path / "2015q4.zip"
    sub_rows = [
        f"{ACCESSION}\t900001\tIDEMPOTENCY TEST CO\t3571\tUS\t10-K\t2015\tFY\t20151231\t20160210"
    ]
    num_rows = [
        f"{ACCESSION}\tAssets\t20151231\t0\tUSD\t1000000",
        f"{ACCESSION}\tLiabilities\t20151231\t0\tUSD\t600000",
        f"{ACCESSION}\tStockholdersEquity\t20151231\t0\tUSD\t400000",
        f"{ACCESSION}\tNetIncomeLoss\t20151231\t4\tUSD\t75000",
    ]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("sub.txt", "\n".join([SUB_HEADER, *sub_rows]) + "\n")
        zf.writestr("num.txt", "\n".join([NUM_HEADER, *num_rows]) + "\n")
    return path


def _counts() -> tuple[int, int, int]:
    with sync_session() as session:
        companies = session.execute(
            select(func.count()).select_from(Company).where(Company.cik == CIK)
        ).scalar_one()
        statements = session.execute(
            select(func.count())
            .select_from(FinancialStatement)
            .where(FinancialStatement.source_accession == ACCESSION)
        ).scalar_one()
        items = session.execute(
            select(func.count())
            .select_from(FinancialLineItem)
            .join(FinancialStatement)
            .where(FinancialStatement.source_accession == ACCESSION)
        ).scalar_one()
    return companies, statements, items


class TestLoader:
    def test_first_run_creates_rows(self, archive: Path) -> None:
        result = ingest_archive(archive)

        assert result.companies_created == 1
        assert result.statements_created == 1
        assert _counts() == (1, 1, 4)

    def test_ingest_is_idempotent(self, archive: Path) -> None:
        """Re-running the same archive must converge, not duplicate."""
        ingest_archive(archive)
        first = _counts()

        second_result = ingest_archive(archive)
        second = _counts()

        assert first == second
        assert second_result.companies_created == 0
        assert second_result.statements_created == 0
        assert second_result.statements_updated == 1

    def test_ingested_company_is_public_reference_data(self, archive: Path) -> None:
        """SEC data is shared by every tenant, so it is stored once with a NULL
        organization_id rather than copied per tenant."""
        ingest_archive(archive)

        with sync_session() as session:
            company = session.execute(select(Company).where(Company.cik == CIK)).scalar_one()
        assert company.organization_id is None

    def test_values_survive_as_exact_decimals(self, archive: Path) -> None:
        """The whole reason value is Numeric rather than float."""
        ingest_archive(archive)

        with sync_session() as session:
            value = session.execute(
                select(FinancialLineItem.value)
                .join(FinancialStatement)
                .where(
                    FinancialStatement.source_accession == ACCESSION,
                    FinancialLineItem.tag == "Assets",
                )
            ).scalar_one()

        assert isinstance(value, Decimal)
        assert value == Decimal("1000000")

    def test_statement_metadata_is_normalised(self, archive: Path) -> None:
        ingest_archive(archive)

        with sync_session() as session:
            statement = session.execute(
                select(FinancialStatement).where(FinancialStatement.source_accession == ACCESSION)
            ).scalar_one()

        assert statement.fiscal_year == 2015
        assert statement.period_end_date == date(2015, 12, 31)
        assert statement.source_dataset == "sec_dera"

    def test_unlabelled_when_company_is_not_in_the_aaer_map(self, archive: Path) -> None:
        ingest_archive(archive)

        with sync_session() as session:
            label = session.execute(
                select(FinancialStatement.is_fraud_label).where(
                    FinancialStatement.source_accession == ACCESSION
                )
            ).scalar_one()

        assert label is None

    def test_label_is_applied_when_the_period_falls_in_a_window(
        self, archive: Path, tmp_path: Path
    ) -> None:
        mapping = tmp_path / "map.csv"
        mapping.write_text(
            "cik,company_name,violation_start,violation_end,aaer_number,match_confidence\n"
            f"{CIK},IDEMPOTENCY TEST CO,2015-01-01,2015-12-31,AAER-TEST,1.00\n",
            encoding="utf-8",
        )

        ingest_archive(archive, load_aaer_mapping(mapping))

        with sync_session() as session:
            statement = session.execute(
                select(FinancialStatement).where(FinancialStatement.source_accession == ACCESSION)
            ).scalar_one()

        assert statement.is_fraud_label is True
        assert statement.fraud_label_source == "sec_aaer"

    def test_relabelling_on_re_ingest_updates_in_place(self, archive: Path, tmp_path: Path) -> None:
        """Labels improve as the mapping table is reviewed. A re-run must pick
        the new label up without creating a second statement row."""
        ingest_archive(archive)

        mapping = tmp_path / "map.csv"
        mapping.write_text(
            "cik,company_name,violation_start,violation_end,aaer_number,match_confidence\n"
            f"{CIK},IDEMPOTENCY TEST CO,2015-01-01,2015-12-31,AAER-TEST,1.00\n",
            encoding="utf-8",
        )
        ingest_archive(archive, load_aaer_mapping(mapping))

        assert _counts() == (1, 1, 4)
        with sync_session() as session:
            label = session.execute(
                select(FinancialStatement.is_fraud_label).where(
                    FinancialStatement.source_accession == ACCESSION
                )
            ).scalar_one()
        assert label is True
