"""Risk scoring and the batch scoring job.

Combines the findings from ``detectors`` into a single 0-100 score per
statement, and persists both the flags and the score.

Scoring design
--------------
The score is a **saturating weighted sum**, not an average and not a count.

* An average would let a statement with one critical finding and nine clean
  checks score lower than one with three medium findings, which inverts the
  priority an auditor actually wants.
* A raw count treats a rounding discrepancy as equal to a broken balance sheet.
* Saturation means the curve flattens as findings accumulate, so no single
  detector can pin the score at the ceiling on its own, while additional
  findings still always move it upward. The value approaches 100
  asymptotically and rounds to it only in the extreme.

The weights are severity-based and deliberately explicit. This is a triage
ordering, not a probability of fraud, and it is documented as such wherever it
surfaces.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from fai.core.logging import get_logger
from fai.db.models import AuditFlag, Company, FinancialLineItem, FinancialStatement
from fai.db.models.enums import FlagSeverity, FlagStatus
from fai.detection.detectors import Finding, check_benford, run_all
from fai.detection.ratios import compute_ratios

log = get_logger(__name__)

# Contribution of one finding at each severity, before saturation.
SEVERITY_WEIGHT: dict[FlagSeverity, float] = {
    FlagSeverity.INFO: 1.0,
    FlagSeverity.LOW: 4.0,
    FlagSeverity.MEDIUM: 12.0,
    FlagSeverity.HIGH: 28.0,
    FlagSeverity.CRITICAL: 55.0,
}

# Controls how quickly the score approaches 100. Chosen so that a single
# critical finding lands around 70 and two land around 88, which matches how a
# reviewer would rank those cases.
SATURATION_CONSTANT = 60.0


def risk_score(findings: Sequence[Finding]) -> float:
    """Combine findings into a 0-100 triage score.

    Uses ``100 * (1 - exp(-total / k))``, which is monotonic in the weighted
    total, always within 0-100, and has no discontinuities for a reviewer to
    trip over when a score moves between refreshes.
    """
    if not findings:
        return 0.0

    total = 0.0
    for finding in findings:
        weight = SEVERITY_WEIGHT.get(finding.severity, 1.0)
        # The detector's own confidence modulates its contribution, but never
        # to zero: a finding that fired at all is worth something.
        confidence = 0.5 + 0.5 * (finding.score if finding.score is not None else 1.0)
        total += weight * min(confidence, 1.0)

    return round(100.0 * (1.0 - math.exp(-total / SATURATION_CONSTANT)), 2)


@dataclass
class ScoringResult:
    statements_scored: int = 0
    flags_written: int = 0
    benford_cohorts: int = 0

    def __str__(self) -> str:
        return (
            f"{self.statements_scored} statements scored, "
            f"{self.flags_written} flags written, "
            f"{self.benford_cohorts} Benford cohorts tested"
        )


def _load_values(
    session: Session, statement_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Decimal]]:
    """Load line items for a batch of statements, keyed by statement."""
    rows = session.execute(
        select(
            FinancialLineItem.statement_id,
            FinancialLineItem.tag,
            FinancialLineItem.value,
        ).where(FinancialLineItem.statement_id.in_(statement_ids))
    ).all()

    grouped: dict[uuid.UUID, dict[str, Decimal]] = defaultdict(dict)
    for statement_id, tag, value in rows:
        grouped[statement_id][tag] = value
    return grouped


def _build_cohorts(
    per_statement_values: dict[uuid.UUID, dict[str, Decimal]],
) -> dict[str, list[float]]:
    """Build peer distributions for every ratio across the batch.

    The cohort is the batch being scored. That is a deliberate simplification:
    a stricter peer group would be same-sector, same-period, and is the obvious
    next refinement. The cohort actually used is recorded on every flag so a
    reviewer always knows what the comparison was against.
    """
    cohorts: dict[str, list[float]] = defaultdict(list)
    for values in per_statement_values.values():
        for name, value in compute_ratios(values).available().items():
            # Guard against infinities from near-zero denominators poisoning the
            # mean and standard deviation for everybody else.
            if math.isfinite(value):
                cohorts[name].append(value)
    return cohorts


def _persist_findings(
    session: Session, statement_id: uuid.UUID, findings: Sequence[Finding]
) -> int:
    """Upsert findings for one statement.

    The unique constraint on (statement_id, flag_type, detection_method) makes
    a re-run idempotent: an existing finding is refreshed in place rather than
    duplicated, and a reviewer's triage status is preserved.
    """
    if not findings:
        return 0

    rows = [
        {
            "statement_id": statement_id,
            "flag_type": finding.flag_type,
            "severity": finding.severity,
            "status": FlagStatus.OPEN,
            "detection_method": finding.detection_method,
            "score": finding.score,
            "description": finding.description,
            "detail": finding.detail,
        }
        for finding in findings
    ]

    statement = pg_insert(AuditFlag).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_flag_statement_type_method",
        set_={
            "severity": statement.excluded.severity,
            "score": statement.excluded.score,
            "description": statement.excluded.description,
            "detail": statement.excluded.detail,
            # status is deliberately absent: re-running detection must not
            # silently reopen a finding a reviewer has already dismissed.
        },
    )
    session.execute(statement)
    return len(rows)


def score_statements(
    session: Session,
    *,
    statement_ids: Sequence[uuid.UUID] | None = None,
    limit: int | None = None,
) -> ScoringResult:
    """Run every detector over a set of statements and persist the results.

    With no ``statement_ids``, scores every statement that has line items.
    """
    query = select(FinancialStatement.id)
    if statement_ids is not None:
        query = query.where(FinancialStatement.id.in_(list(statement_ids)))
    if limit is not None:
        query = query.limit(limit)

    ids = list(session.execute(query).scalars().all())
    if not ids:
        return ScoringResult()

    per_statement = _load_values(session, ids)
    cohorts = _build_cohorts(per_statement)

    result = ScoringResult()
    for statement_id in ids:
        values = per_statement.get(statement_id)
        if not values:
            # A statement with no line items cannot be analysed. Scoring it zero
            # would present "no data" as "no risk".
            continue

        findings = run_all(values, cohort=cohorts)
        result.flags_written += _persist_findings(session, statement_id, findings)

        statement = session.get(FinancialStatement, statement_id)
        if statement is not None:
            statement.risk_score = risk_score(findings)
            statement.risk_scored_at = datetime.now(UTC)
        result.statements_scored += 1

    session.flush()
    log.info("scoring_complete", summary=str(result))
    return result


def score_benford_by_company(session: Session, *, min_values: int = 80) -> int:
    """Run the Benford test per company, across all of its filings.

    A single filing carries far too few values for the test to mean anything,
    so the cohort is every value the company has ever reported. The flag is
    attached to that company's most recent statement, since a flag has to hang
    off something, and the cohort is recorded in the detail payload.
    """
    companies = session.execute(
        select(Company.id, Company.name)
        .join(FinancialStatement, FinancialStatement.company_id == Company.id)
        .distinct()
    ).all()

    flagged = 0
    for company_id, company_name in companies:
        rows = (
            session.execute(
                select(FinancialLineItem.value)
                .join(FinancialStatement, FinancialLineItem.statement_id == FinancialStatement.id)
                .where(FinancialStatement.company_id == company_id)
            )
            .scalars()
            .all()
        )

        if len(rows) < min_values:
            continue

        latest = session.execute(
            select(FinancialStatement.id)
            .where(FinancialStatement.company_id == company_id)
            .order_by(
                FinancialStatement.fiscal_year.desc(),
                FinancialStatement.period_end_date.desc().nullslast(),
            )
            .limit(1)
        ).scalar_one_or_none()
        if latest is None:
            continue

        findings = check_benford(
            list(rows),
            cohort_description=(
                f"All {len(rows)} reported values for {company_name} across every ingested filing."
            ),
        )
        flagged += _persist_findings(session, latest, findings)

    session.flush()
    return flagged
