"""Deterministic anomaly detectors.

Every finding in the platform originates here. Each detector is a pure function
over a statement's line items and, where relevant, a peer cohort: same inputs,
same flags, every time. That reproducibility is a hard requirement for anything
audit-facing, and it is why no detector consults a model that samples.

Each detector returns evidence, not just a verdict. The ``detail`` payload
carries the observed value, the expected range, and how the expectation was
formed, so that a reviewer can disagree with the finding on its merits and so
that the LLM explanation layer has something concrete to describe without ever
seeing the underlying dataset.

Thresholds
----------
The thresholds below are screening heuristics drawn from standard financial
analysis, not statutory limits. They are deliberately gathered in one place and
named, rather than scattered as literals, so they can be reviewed and tuned as
a set. A flag is a prompt for human attention, never a conclusion.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from fai.db.models.enums import DetectionMethod, FlagSeverity
from fai.detection.benford import analyse as benford_analyse
from fai.detection.ratios import Ratios, accounting_identity_error, compute_ratios

# The accounting identity should hold to the cent. A tolerance of 0.5% absorbs
# genuine rounding and presentation differences; beyond it, something is either
# mis-tagged or misstated.
IDENTITY_TOLERANCE = Decimal("0.005")

# Liquidity below 1.0 means current liabilities exceed current assets.
CURRENT_RATIO_FLOOR = 1.0
CURRENT_RATIO_SEVERE = 0.75

# Leverage. Above 3.0 is high for most sectors; above 6.0 is extreme.
DEBT_TO_EQUITY_CEILING = 3.0
DEBT_TO_EQUITY_SEVERE = 6.0

# Accruals: reported earnings far above the cash actually generated. One of the
# most durable empirical markers of earnings management.
ACCRUALS_CEILING = 0.10
ACCRUALS_SEVERE = 0.25

# Margins outside this band are implausible for an operating business and
# usually indicate a tagging error or a restatement.
NET_MARGIN_CEILING = 0.60
NET_MARGIN_FLOOR = -1.0

# Standard deviations from the peer cohort mean before a ratio is an outlier.
ZSCORE_THRESHOLD = 3.0
# A cohort smaller than this has a standard deviation too unstable to compare
# against; z-scores computed on five companies are noise.
MIN_COHORT = 20


@dataclass(frozen=True)
class Finding:
    """One detector output, ready to become an ``audit_flags`` row."""

    flag_type: str
    severity: FlagSeverity
    detection_method: DetectionMethod
    description: str
    score: float | None = None
    detail: dict[str, object] = field(default_factory=dict)


Values = dict[str, Decimal]


def _severity_for(value: float, *, warn: float, severe: float, above: bool) -> FlagSeverity:
    """Bucket a continuous measure into a severity."""
    if above:
        return FlagSeverity.HIGH if value >= severe else FlagSeverity.MEDIUM
    return FlagSeverity.HIGH if value <= severe else FlagSeverity.MEDIUM


# ---------------------------------------------------------------------------
# Structural checks: internal consistency of a single filing
# ---------------------------------------------------------------------------
def check_accounting_identity(values: Values) -> list[Finding]:
    """Assets must equal liabilities plus equity.

    This is not a heuristic. It is an identity that holds by construction in
    double-entry accounting, so a filing that fails it has either been tagged
    incorrectly or does not balance. Either warrants a look.
    """
    error = accounting_identity_error(values)
    if error is None or error <= IDENTITY_TOLERANCE:
        return []

    assets = values["Assets"]
    liabilities = values["Liabilities"]
    equity = values["StockholdersEquity"]
    difference = assets - (liabilities + equity)

    return [
        Finding(
            flag_type="accounting_identity_violation",
            severity=(FlagSeverity.CRITICAL if error > Decimal("0.05") else FlagSeverity.HIGH),
            detection_method=DetectionMethod.ACCOUNTING_IDENTITY,
            description=(
                "Assets do not equal liabilities plus equity. The balance sheet is "
                f"out by {float(error):.2%} of total assets."
            ),
            score=min(float(error), 1.0),
            detail={
                "assets": str(assets),
                "liabilities": str(liabilities),
                "equity": str(equity),
                "difference": str(difference),
                "relative_error": float(error),
                "tolerance": float(IDENTITY_TOLERANCE),
            },
        )
    ]


def check_ratio_thresholds(ratios: Ratios) -> list[Finding]:
    """Screen computed ratios against conventional bounds."""
    findings: list[Finding] = []

    if ratios.current_ratio is not None and ratios.current_ratio < CURRENT_RATIO_FLOOR:
        findings.append(
            Finding(
                flag_type="low_liquidity",
                severity=_severity_for(
                    ratios.current_ratio,
                    warn=CURRENT_RATIO_FLOOR,
                    severe=CURRENT_RATIO_SEVERE,
                    above=False,
                ),
                detection_method=DetectionMethod.RATIO_THRESHOLD,
                description=(
                    f"Current ratio of {ratios.current_ratio:.2f} is below "
                    f"{CURRENT_RATIO_FLOOR:.2f}: current liabilities exceed current assets."
                ),
                score=round(min(1.0, (CURRENT_RATIO_FLOOR - ratios.current_ratio)), 4),
                detail={
                    "ratio": "current_ratio",
                    "observed": round(ratios.current_ratio, 4),
                    "threshold": CURRENT_RATIO_FLOOR,
                    "direction": "below",
                },
            )
        )

    if ratios.debt_to_equity is not None and ratios.debt_to_equity > DEBT_TO_EQUITY_CEILING:
        findings.append(
            Finding(
                flag_type="high_leverage",
                severity=_severity_for(
                    ratios.debt_to_equity,
                    warn=DEBT_TO_EQUITY_CEILING,
                    severe=DEBT_TO_EQUITY_SEVERE,
                    above=True,
                ),
                detection_method=DetectionMethod.RATIO_THRESHOLD,
                description=(
                    f"Debt-to-equity of {ratios.debt_to_equity:.2f} exceeds "
                    f"{DEBT_TO_EQUITY_CEILING:.2f}."
                ),
                score=round(min(1.0, ratios.debt_to_equity / (DEBT_TO_EQUITY_SEVERE * 2)), 4),
                detail={
                    "ratio": "debt_to_equity",
                    "observed": round(ratios.debt_to_equity, 4),
                    "threshold": DEBT_TO_EQUITY_CEILING,
                    "direction": "above",
                },
            )
        )

    if ratios.accruals_ratio is not None and ratios.accruals_ratio > ACCRUALS_CEILING:
        findings.append(
            Finding(
                flag_type="high_accruals",
                severity=_severity_for(
                    ratios.accruals_ratio,
                    warn=ACCRUALS_CEILING,
                    severe=ACCRUALS_SEVERE,
                    above=True,
                ),
                detection_method=DetectionMethod.RATIO_THRESHOLD,
                description=(
                    f"Accruals ratio of {ratios.accruals_ratio:.2%} of assets: reported "
                    "earnings substantially exceed the cash generated by operations."
                ),
                score=round(min(1.0, ratios.accruals_ratio / ACCRUALS_SEVERE), 4),
                detail={
                    "ratio": "accruals_ratio",
                    "observed": round(ratios.accruals_ratio, 4),
                    "threshold": ACCRUALS_CEILING,
                    "direction": "above",
                    "interpretation": (
                        "Net income materially above operating cash flow is a "
                        "recognised marker of earnings management. It is not proof of "
                        "one: rapid growth and working-capital swings produce the same "
                        "signature."
                    ),
                },
            )
        )

    if ratios.net_margin is not None and not (
        NET_MARGIN_FLOOR <= ratios.net_margin <= NET_MARGIN_CEILING
    ):
        findings.append(
            Finding(
                flag_type="implausible_margin",
                severity=FlagSeverity.MEDIUM,
                detection_method=DetectionMethod.RATIO_THRESHOLD,
                description=(
                    f"Net margin of {ratios.net_margin:.2%} falls outside the plausible "
                    "range for an operating business, which usually indicates a tagging "
                    "error or a restatement."
                ),
                score=0.5,
                detail={
                    "ratio": "net_margin",
                    "observed": round(ratios.net_margin, 4),
                    "plausible_range": [NET_MARGIN_FLOOR, NET_MARGIN_CEILING],
                },
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Cohort checks: this filing against its peers
# ---------------------------------------------------------------------------
def check_ratio_outliers(ratios: Ratios, cohort: Mapping[str, Sequence[float]]) -> list[Finding]:
    """Flag ratios far from the peer cohort mean.

    ``cohort`` maps a ratio name to the values observed across comparable
    filings, typically the same sector and period. A ratio that is unremarkable
    in isolation can be a clear outlier against peers, which is exactly the
    comparison an auditor makes by hand.
    """
    findings: list[Finding] = []

    for name, observed in ratios.available().items():
        peers = cohort.get(name)
        if peers is None or len(peers) < MIN_COHORT:
            # Too few peers for the standard deviation to mean anything.
            continue

        mean = statistics.fmean(peers)
        stdev = statistics.pstdev(peers)
        if stdev == 0:
            # Every peer reports the same value; there is no scale on which to
            # call anything an outlier.
            continue

        z_score = (observed - mean) / stdev
        if abs(z_score) < ZSCORE_THRESHOLD:
            continue

        findings.append(
            Finding(
                flag_type=f"outlier_{name}",
                severity=(
                    FlagSeverity.HIGH
                    if abs(z_score) >= ZSCORE_THRESHOLD * 2
                    else FlagSeverity.MEDIUM
                ),
                detection_method=DetectionMethod.ZSCORE_OUTLIER,
                description=(
                    f"{name.replace('_', ' ').capitalize()} of {observed:.4g} is "
                    f"{abs(z_score):.1f} standard deviations "
                    f"{'above' if z_score > 0 else 'below'} the peer group mean."
                ),
                score=round(min(1.0, abs(z_score) / (ZSCORE_THRESHOLD * 3)), 4),
                detail={
                    "ratio": name,
                    "observed": round(observed, 6),
                    "cohort_mean": round(mean, 6),
                    "cohort_stdev": round(stdev, 6),
                    "cohort_size": len(peers),
                    "z_score": round(z_score, 3),
                    "threshold": ZSCORE_THRESHOLD,
                },
            )
        )

    return findings


def check_benford(values: list[Decimal], *, cohort_description: str) -> list[Finding]:
    """Run the Benford first-digit test over a cohort of reported values."""
    result = benford_analyse(values)

    if not result.sufficient_sample or result.conforms:
        return []

    severe = result.chi_square > 20.090  # 99% critical value, 8 dof
    detail = result.as_detail()
    detail["cohort"] = cohort_description
    detail["interpretation"] = (
        "A poor fit to the expected leading-digit distribution indicates the "
        "figures are worth examining. It is not evidence of fraud on its own: "
        "constrained ranges, heavy rounding, and regulated pricing all produce "
        "non-Benford distributions legitimately."
    )

    return [
        Finding(
            flag_type="benford_deviation",
            severity=FlagSeverity.HIGH if severe else FlagSeverity.MEDIUM,
            detection_method=DetectionMethod.BENFORD_LAW,
            description=(
                "Reported values deviate from the expected Benford leading-digit "
                f"distribution (chi-square {result.chi_square:.1f} over "
                f"{result.sample_size} values)."
            ),
            score=round(min(1.0, result.chi_square / 40.0), 4),
            detail=detail,
        )
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run_all(
    values: Values,
    *,
    cohort: Mapping[str, Sequence[float]] | None = None,
) -> list[Finding]:
    """Run every single-statement detector and return the findings.

    The Benford test is not included here: it operates over a cohort of values
    across filings, and a single statement carries far too few to be meaningful.
    It is driven separately by the scoring job.
    """
    ratios = compute_ratios(values)
    findings = check_accounting_identity(values)
    findings.extend(check_ratio_thresholds(ratios))
    if cohort:
        findings.extend(check_ratio_outliers(ratios, cohort))
    return findings
