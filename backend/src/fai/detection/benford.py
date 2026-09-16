"""Benford's law leading-digit analysis.

Naturally occurring financial figures spanning several orders of magnitude have
a leading digit distributed as ``log10(1 + 1/d)``: about 30% of values begin
with 1, about 4.6% with 9. Fabricated figures rarely do, because people
inventing numbers distribute first digits far more evenly.

Unit of analysis
----------------
The project plan specified running this over "transaction amounts". The SEC
DERA datasets contain aggregated statement line items and have no transactions,
so there is nothing at that granularity to test.

This module therefore operates over a **cohort**: the line-item values of one
company across several periods, or of several companies within one period. A
single filing carries a few dozen values, which is nowhere near enough for the
test to mean anything, so the cohort is the unit and the cohort used is recorded
on every flag it produces.

Interpretation
--------------
A poor fit is evidence that a set of numbers is worth a human look. It is not
evidence of fraud, and this module deliberately reports a statistic and a
sample size rather than a verdict. Small samples fail the test routinely for
entirely innocent reasons, which is why ``MIN_SAMPLE`` exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

# Below this, the chi-square statistic is dominated by sampling noise and the
# test says nothing useful. Published guidance ranges from 50 to several
# hundred; 80 is a deliberately conservative floor for this corpus.
MIN_SAMPLE = 80

# Expected first-digit frequencies, digits 1 through 9.
EXPECTED_FREQUENCIES: tuple[float, ...] = tuple(math.log10(1 + 1 / digit) for digit in range(1, 10))

# Chi-square critical values with 8 degrees of freedom.
CHI2_CRITICAL_95 = 15.507
CHI2_CRITICAL_99 = 20.090


@dataclass(frozen=True)
class BenfordResult:
    """Outcome of a Benford test over one cohort."""

    sample_size: int
    observed_counts: tuple[int, ...]
    observed_frequencies: tuple[float, ...]
    expected_frequencies: tuple[float, ...]
    chi_square: float
    # Mean absolute deviation, the statistic auditors more commonly quote
    # because, unlike chi-square, it does not grow with sample size.
    mean_absolute_deviation: float
    conforms: bool
    sufficient_sample: bool

    def as_detail(self) -> dict[str, object]:
        """Evidence payload for an audit flag, and later for the LLM prompt."""
        return {
            "sample_size": self.sample_size,
            "chi_square": round(self.chi_square, 3),
            "chi_square_critical_95": CHI2_CRITICAL_95,
            "mean_absolute_deviation": round(self.mean_absolute_deviation, 5),
            "observed_frequencies": [round(f, 4) for f in self.observed_frequencies],
            "expected_frequencies": [round(f, 4) for f in self.expected_frequencies],
            "digits": list(range(1, 10)),
        }


def leading_digit(value: Decimal) -> int | None:
    """Return the leading significant digit of a value, or None.

    Zero has no leading significant digit. The sign is discarded: a loss of
    -4,200 carries the same digit information as a gain of 4,200.
    """
    magnitude = abs(value)
    if magnitude == 0:
        return None

    # Taken from the decimal string rather than by repeated division, which
    # would reintroduce the floating-point error that Numeric storage exists to
    # avoid.
    digits = str(magnitude).lstrip("0.").replace(".", "").lstrip("0")
    if not digits:
        return None
    first = digits[0]
    return int(first) if first.isdigit() and first != "0" else None


def analyse(values: list[Decimal]) -> BenfordResult:
    """Run the first-digit test over a cohort of values."""
    counts = [0] * 9
    for value in values:
        digit = leading_digit(value)
        if digit is not None:
            counts[digit - 1] += 1

    total = sum(counts)
    if total == 0:
        return BenfordResult(
            sample_size=0,
            observed_counts=tuple(counts),
            observed_frequencies=tuple([0.0] * 9),
            expected_frequencies=EXPECTED_FREQUENCIES,
            chi_square=0.0,
            mean_absolute_deviation=0.0,
            conforms=True,
            sufficient_sample=False,
        )

    observed = tuple(count / total for count in counts)

    chi_square = 0.0
    for index, expected_frequency in enumerate(EXPECTED_FREQUENCIES):
        expected_count = expected_frequency * total
        # expected_count is never zero for any digit once total > 0, since every
        # expected frequency is strictly positive.
        chi_square += (counts[index] - expected_count) ** 2 / expected_count

    mad = sum(abs(observed[i] - EXPECTED_FREQUENCIES[i]) for i in range(9)) / 9

    sufficient = total >= MIN_SAMPLE
    return BenfordResult(
        sample_size=total,
        observed_counts=tuple(counts),
        observed_frequencies=observed,
        expected_frequencies=EXPECTED_FREQUENCIES,
        chi_square=chi_square,
        mean_absolute_deviation=mad,
        # An insufficient sample is reported as conforming, not as failing.
        # Flagging every small cohort would bury the real findings in noise.
        conforms=(not sufficient) or chi_square <= CHI2_CRITICAL_95,
        sufficient_sample=sufficient,
    )
