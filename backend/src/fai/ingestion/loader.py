"""Database loader for parsed filings.

Everything here is an upsert. Ingestion runs over multi-hundred-megabyte
archives and is expected to be interrupted, re-run, and run again over an
overlapping quarter, so a second run must converge to the same state rather
than duplicating or failing.

The unique constraints that make this possible are
``uq_statement_accession`` and ``uq_line_item_statement_tag``; see
docs/data-model.md.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from fai.core.logging import get_logger
from fai.db.models import Company, FinancialLineItem, FinancialStatement
from fai.ingestion.aaer import AaerLabelIndex
from fai.ingestion.sec_dera import ParsedFact, ParsedSubmission

log = get_logger(__name__)

# Rows per INSERT. Large enough to amortise round trips, small enough that a
# single statement stays well inside Postgres parameter limits.
BATCH_SIZE = 1_000


def _key_to_id(
    session: Session, statement: Select[tuple[str | None, uuid.UUID]]
) -> dict[str, uuid.UUID]:
    """Run a two-column (key, id) select into a typed mapping.

    SQLAlchemy types the rows as Sequence[Row[...]], which dict() cannot infer a
    key/value type from. Narrowing once here keeps the call sites readable.
    """
    return {str(key): value for key, value in session.execute(statement).all()}


@dataclass
class LoadResult:
    companies_created: int = 0
    statements_created: int = 0
    statements_updated: int = 0
    line_items_written: int = 0
    labels_applied: int = 0

    def __str__(self) -> str:
        return (
            f"companies +{self.companies_created}, "
            f"statements +{self.statements_created}/~{self.statements_updated}, "
            f"line items {self.line_items_written}, "
            f"labels {self.labels_applied}"
        )


def upsert_companies(
    session: Session, submissions: list[ParsedSubmission]
) -> tuple[dict[str, uuid.UUID], int]:
    """Ensure a public company row exists for every CIK in the batch.

    Returns a CIK-to-id map. Companies ingested from SEC data are public
    reference rows, so ``organization_id`` is NULL and they are shared by every
    tenant.
    """
    # One row per CIK. A quarterly archive contains several filings per company
    # and the insert must not carry duplicate conflict targets.
    by_cik: dict[str, ParsedSubmission] = {}
    for submission in submissions:
        by_cik.setdefault(submission.cik, submission)

    if not by_cik:
        return {}, 0

    existing = _key_to_id(
        session,
        select(Company.cik, Company.id).where(
            Company.cik.in_(by_cik.keys()), Company.organization_id.is_(None)
        ),
    )

    new_ciks = [cik for cik in by_cik if cik not in existing]
    for start in range(0, len(new_ciks), BATCH_SIZE):
        chunk = new_ciks[start : start + BATCH_SIZE]
        rows = [
            {
                "organization_id": None,
                "name": by_cik[cik].company_name,
                "cik": cik,
                "sic_code": by_cik[cik].sic_code,
                "country": by_cik[cik].country,
            }
            for cik in chunk
        ]
        statement = pg_insert(Company).values(rows)
        # The conflict target is the partial unique index on public CIKs, so a
        # concurrent ingest of the same quarter cannot produce duplicates.
        statement = statement.on_conflict_do_nothing(
            index_where=Company.organization_id.is_(None) & Company.cik.isnot(None),
            index_elements=[Company.cik],
        )
        session.execute(statement)

    session.flush()

    resolved = _key_to_id(
        session,
        select(Company.cik, Company.id).where(
            Company.cik.in_(by_cik.keys()), Company.organization_id.is_(None)
        ),
    )
    return resolved, len(resolved) - len(existing)


def upsert_statements(
    session: Session,
    submissions: list[ParsedSubmission],
    company_ids: dict[str, uuid.UUID],
    labels: AaerLabelIndex | None = None,
) -> tuple[dict[str, uuid.UUID], LoadResult]:
    """Ensure a statement row exists for every submission.

    Returns an accession-to-id map for the fact loader.
    """
    result = LoadResult()
    if not submissions:
        return {}, result

    accessions = [s.accession for s in submissions]
    existing = _key_to_id(
        session,
        select(FinancialStatement.source_accession, FinancialStatement.id).where(
            FinancialStatement.source_accession.in_(accessions)
        ),
    )

    rows = []
    for submission in submissions:
        company_id = company_ids.get(submission.cik)
        if company_id is None:
            continue

        label = labels.label(submission.cik, submission.period_end_date) if labels else None
        if label is not None:
            result.labels_applied += 1

        rows.append(
            {
                "organization_id": None,
                "company_id": company_id,
                "fiscal_year": submission.fiscal_year,
                "fiscal_period": submission.fiscal_period,
                "filing_type": submission.filing_type,
                "period_end_date": submission.period_end_date,
                "filed_date": submission.filed_date,
                "source_dataset": "sec_dera",
                "source_accession": submission.accession,
                "is_fraud_label": label,
                "fraud_label_source": "sec_aaer" if label is not None else None,
            }
        )

    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start : start + BATCH_SIZE]
        statement = pg_insert(FinancialStatement).values(chunk)
        # Re-running over the same quarter refreshes the label and the dates but
        # must never duplicate the statement or orphan its line items.
        statement = statement.on_conflict_do_update(
            constraint="uq_statement_accession",
            set_={
                "period_end_date": statement.excluded.period_end_date,
                "filed_date": statement.excluded.filed_date,
                "is_fraud_label": statement.excluded.is_fraud_label,
                "fraud_label_source": statement.excluded.fraud_label_source,
                "updated_at": datetime.now(UTC),
            },
        )
        session.execute(statement)

    session.flush()

    resolved = _key_to_id(
        session,
        select(FinancialStatement.source_accession, FinancialStatement.id).where(
            FinancialStatement.source_accession.in_(accessions)
        ),
    )
    result.statements_created = len(resolved) - len(existing)
    result.statements_updated = len(existing)
    return resolved, result


def upsert_facts(
    session: Session,
    facts: list[ParsedFact],
    statement_ids: dict[str, uuid.UUID],
) -> int:
    """Write line items, replacing any previous value for the same tag."""
    grouped: dict[uuid.UUID, list[ParsedFact]] = defaultdict(list)
    for fact in facts:
        statement_id = statement_ids.get(fact.accession)
        if statement_id is not None:
            grouped[statement_id].append(fact)

    rows = [
        {
            "statement_id": statement_id,
            "tag": fact.tag,
            "label": None,
            "value": fact.value,
            "unit": fact.unit,
            "statement_section": fact.section,
        }
        for statement_id, statement_facts in grouped.items()
        for fact in statement_facts
    ]

    written = 0
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start : start + BATCH_SIZE]
        statement = pg_insert(FinancialLineItem).values(chunk)
        statement = statement.on_conflict_do_update(
            constraint="uq_line_item_statement_tag",
            set_={
                "value": statement.excluded.value,
                "unit": statement.excluded.unit,
                "statement_section": statement.excluded.statement_section,
            },
        )
        session.execute(statement)
        written += len(chunk)

    session.flush()
    return written
