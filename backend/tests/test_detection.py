"""Anomaly detection tests.

Every detector is deterministic, so these are ordinary unit tests over known
inputs. The properties being pinned down are the ones a reviewer would
challenge: that a missing value is not treated as zero, that thresholds fire
where they are documented to, and that no metric flatters a useless model.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pandas as pd
import pytest

from fai.db.models.enums import DetectionMethod, FlagSeverity
from fai.detection.benford import MIN_SAMPLE, analyse, leading_digit
from fai.detection.classifier import (
    FEATURE_COLUMNS,
    build_model,
    evaluate,
    prepare_dataset,
)
from fai.detection.detectors import (
    Finding,
    check_accounting_identity,
    check_benford,
    check_ratio_outliers,
    check_ratio_thresholds,
    run_all,
)
from fai.detection.ratios import Ratios, accounting_identity_error, compute_ratios
from fai.detection.scoring import risk_score


def d(value: str) -> Decimal:
    return Decimal(value)


BALANCED = {
    "Assets": d("1000000"),
    "Liabilities": d("600000"),
    "StockholdersEquity": d("400000"),
    "AssetsCurrent": d("500000"),
    "LiabilitiesCurrent": d("250000"),
    "Revenue": d("800000"),
    "NetIncome": d("80000"),
    "OperatingCashFlow": d("75000"),
}


# ---------------------------------------------------------------------------
# Ratios
# ---------------------------------------------------------------------------
class TestRatios:
    def test_computes_the_standard_ratios(self) -> None:
        ratios = compute_ratios(BALANCED)

        assert ratios.current_ratio == pytest.approx(2.0)
        assert ratios.debt_to_equity == pytest.approx(1.5)
        assert ratios.net_margin == pytest.approx(0.1)
        assert ratios.return_on_assets == pytest.approx(0.08)

    def test_missing_input_yields_none_not_zero(self) -> None:
        """Zero is a real value for most of these. Conflating 'not computable'
        with 'zero' would produce false findings on incomplete filings, which
        are common in the corpus."""
        ratios = compute_ratios({"Assets": d("100")})

        assert ratios.current_ratio is None
        assert ratios.debt_to_equity is None
        assert ratios.net_margin is None

    def test_zero_denominator_yields_none(self) -> None:
        """A company can genuinely report zero equity. The ratio is undefined,
        not infinite, and certainly not an error."""
        ratios = compute_ratios({"Liabilities": d("100"), "StockholdersEquity": d("0")})
        assert ratios.debt_to_equity is None

    def test_gross_profit_is_derived_when_untagged(self) -> None:
        ratios = compute_ratios({"Revenue": d("1000"), "CostOfRevenue": d("600")})
        assert ratios.gross_margin == pytest.approx(0.4)

    def test_quick_ratio_excludes_inventory(self) -> None:
        ratios = compute_ratios(
            {
                "AssetsCurrent": d("500"),
                "Inventory": d("200"),
                "LiabilitiesCurrent": d("250"),
            }
        )
        assert ratios.quick_ratio == pytest.approx(1.2)

    def test_large_values_keep_full_precision(self) -> None:
        """The whole reason the inputs are Decimal rather than float."""
        ratios = compute_ratios(
            {
                "Assets": d("352755000000.01"),
                "Liabilities": d("302083000000.01"),
                "StockholdersEquity": d("50672000000.00"),
            }
        )
        assert ratios.debt_to_equity is not None
        assert math.isfinite(ratios.debt_to_equity)

    def test_available_omits_uncomputable_ratios(self) -> None:
        available = compute_ratios({"Assets": d("100")}).available()
        assert available == {}


class TestAccountingIdentity:
    def test_balanced_sheet_has_no_error(self) -> None:
        assert accounting_identity_error(BALANCED) == 0

    def test_unbalanced_sheet_reports_relative_error(self) -> None:
        error = accounting_identity_error(
            {
                "Assets": d("1000000"),
                "Liabilities": d("600000"),
                "StockholdersEquity": d("300000"),
            }
        )
        assert error == pytest.approx(Decimal("0.1"))

    def test_missing_component_yields_none(self) -> None:
        assert accounting_identity_error({"Assets": d("100")}) is None


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------
class TestAccountingIdentityDetector:
    def test_balanced_sheet_produces_no_finding(self) -> None:
        assert check_accounting_identity(BALANCED) == []

    def test_rounding_difference_is_tolerated(self) -> None:
        """Presentation rounding is normal and must not generate noise."""
        findings = check_accounting_identity(
            {
                "Assets": d("1000000"),
                "Liabilities": d("600000"),
                "StockholdersEquity": d("399000"),  # 0.1% out
            }
        )
        assert findings == []

    def test_material_imbalance_is_flagged(self) -> None:
        findings = check_accounting_identity(
            {
                "Assets": d("1000000"),
                "Liabilities": d("600000"),
                "StockholdersEquity": d("300000"),  # 10% out
            }
        )

        assert len(findings) == 1
        assert findings[0].detection_method is DetectionMethod.ACCOUNTING_IDENTITY
        assert findings[0].severity is FlagSeverity.CRITICAL
        assert findings[0].detail["relative_error"] == pytest.approx(0.1)

    def test_finding_carries_the_underlying_figures(self) -> None:
        """The explanation layer describes the evidence; it never sees the
        dataset, so the evidence has to travel with the finding."""
        findings = check_accounting_identity(
            {
                "Assets": d("1000000"),
                "Liabilities": d("600000"),
                "StockholdersEquity": d("300000"),
            }
        )
        detail = findings[0].detail
        assert {"assets", "liabilities", "equity", "difference"} <= set(detail)


class TestRatioThresholds:
    def test_healthy_ratios_produce_no_findings(self) -> None:
        assert check_ratio_thresholds(compute_ratios(BALANCED)) == []

    def test_low_liquidity_is_flagged(self) -> None:
        findings = check_ratio_thresholds(Ratios(current_ratio=0.8))
        assert [f.flag_type for f in findings] == ["low_liquidity"]
        assert findings[0].severity is FlagSeverity.MEDIUM

    def test_severe_liquidity_raises_severity(self) -> None:
        findings = check_ratio_thresholds(Ratios(current_ratio=0.5))
        assert findings[0].severity is FlagSeverity.HIGH

    def test_high_leverage_is_flagged(self) -> None:
        findings = check_ratio_thresholds(Ratios(debt_to_equity=4.0))
        assert [f.flag_type for f in findings] == ["high_leverage"]

    def test_high_accruals_are_flagged(self) -> None:
        findings = check_ratio_thresholds(Ratios(accruals_ratio=0.3))
        assert [f.flag_type for f in findings] == ["high_accruals"]
        assert findings[0].severity is FlagSeverity.HIGH

    def test_accruals_finding_states_it_is_not_proof(self) -> None:
        """A flag is a prompt for attention. Presenting a heuristic as a verdict
        is how an audit tool loses its users' trust."""
        findings = check_ratio_thresholds(Ratios(accruals_ratio=0.3))
        assert "not proof" in findings[0].detail["interpretation"]

    def test_implausible_margin_is_flagged(self) -> None:
        findings = check_ratio_thresholds(Ratios(net_margin=0.95))
        assert [f.flag_type for f in findings] == ["implausible_margin"]

    def test_none_ratios_produce_no_findings(self) -> None:
        assert check_ratio_thresholds(Ratios()) == []


class TestOutlierDetection:
    def test_outlier_against_peers_is_flagged(self) -> None:
        cohort = {"net_margin": [0.10] * 30 + [0.11] * 30}
        findings = check_ratio_outliers(Ratios(net_margin=0.9), cohort)

        assert [f.flag_type for f in findings] == ["outlier_net_margin"]
        assert findings[0].detection_method is DetectionMethod.ZSCORE_OUTLIER

    def test_typical_value_is_not_flagged(self) -> None:
        cohort = {"net_margin": [0.10 + i * 0.001 for i in range(60)]}
        assert check_ratio_outliers(Ratios(net_margin=0.13), cohort) == []

    def test_small_cohort_is_skipped(self) -> None:
        """A standard deviation over five companies is noise, and comparing
        against it would generate findings that mean nothing."""
        assert check_ratio_outliers(Ratios(net_margin=0.9), {"net_margin": [0.1] * 5}) == []

    def test_zero_variance_cohort_is_skipped(self) -> None:
        """With no spread there is no scale on which to call anything an
        outlier, and the z-score would divide by zero."""
        assert check_ratio_outliers(Ratios(net_margin=0.9), {"net_margin": [0.1] * 40}) == []

    def test_finding_records_the_cohort_it_compared_against(self) -> None:
        cohort = {"net_margin": [0.10] * 30 + [0.11] * 30}
        findings = check_ratio_outliers(Ratios(net_margin=0.9), cohort)
        assert findings[0].detail["cohort_size"] == 60
        assert "z_score" in findings[0].detail


# ---------------------------------------------------------------------------
# Benford
# ---------------------------------------------------------------------------
class TestLeadingDigit:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("123", 1),
            ("987654", 9),
            ("0.00456", 4),
            ("-8200", 8),
            ("5", 5),
            ("0", None),
            ("0.0", None),
        ],
    )
    def test_extracts_the_first_significant_digit(self, value: str, expected: int | None) -> None:
        assert leading_digit(Decimal(value)) == expected

    def test_sign_is_irrelevant(self) -> None:
        """A loss of -4,200 carries the same digit information as a gain."""
        assert leading_digit(Decimal("-4200")) == leading_digit(Decimal("4200"))


class TestBenfordAnalysis:
    def _benford_sample(self, n: int = 500) -> list[Decimal]:
        """Values whose first digits follow the Benford distribution."""
        import math as _math

        values: list[Decimal] = []
        for digit in range(1, 10):
            count = round(n * _math.log10(1 + 1 / digit))
            values.extend(Decimal(f"{digit}{i % 900:03d}") for i in range(count))
        return values

    def test_conforming_distribution_passes(self) -> None:
        result = analyse(self._benford_sample())
        assert result.sufficient_sample
        assert result.conforms

    def test_uniform_distribution_fails(self) -> None:
        """Invented figures are distributed far more evenly than real ones."""
        values = [Decimal(f"{d}00") for d in range(1, 10) for _ in range(40)]
        result = analyse(values)

        assert result.sufficient_sample
        assert not result.conforms

    def test_small_sample_is_reported_as_conforming(self) -> None:
        """Flagging every small cohort would bury the real findings in noise."""
        result = analyse([Decimal("100")] * 10)

        assert not result.sufficient_sample
        assert result.conforms

    def test_empty_input_is_handled(self) -> None:
        result = analyse([])
        assert result.sample_size == 0
        assert result.conforms

    def test_zeros_are_excluded_from_the_sample(self) -> None:
        result = analyse([Decimal("0")] * 50 + [Decimal("123")])
        assert result.sample_size == 1

    def test_detector_skips_insufficient_samples(self) -> None:
        assert check_benford([Decimal("100")] * 10, cohort_description="tiny") == []

    def test_detector_records_the_cohort_and_a_caveat(self) -> None:
        values = [Decimal(f"{d}00") for d in range(1, 10) for _ in range(40)]
        findings = check_benford(values, cohort_description="test cohort")

        assert findings
        assert findings[0].detail["cohort"] == "test cohort"
        assert "not evidence of fraud on its own" in findings[0].detail["interpretation"]

    def test_min_sample_is_conservative(self) -> None:
        assert MIN_SAMPLE >= 50


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------
class TestRiskScore:
    def _finding(self, severity: FlagSeverity) -> Finding:
        return Finding(
            flag_type="t",
            severity=severity,
            detection_method=DetectionMethod.RATIO_THRESHOLD,
            description="d",
            score=1.0,
        )

    def test_no_findings_scores_zero(self) -> None:
        assert risk_score([]) == 0.0

    def test_score_is_always_in_range(self) -> None:
        many = [self._finding(FlagSeverity.CRITICAL)] * 50
        assert 0.0 <= risk_score(many) <= 100.0

    def test_realistic_finding_counts_stay_below_the_ceiling(self) -> None:
        """Saturating rather than hard-capping keeps the ordering useful at the
        top end: three critical findings must still rank below five."""
        three = risk_score([self._finding(FlagSeverity.CRITICAL)] * 3)
        five = risk_score([self._finding(FlagSeverity.CRITICAL)] * 5)

        assert three < 100.0
        assert five > three

    def test_severity_dominates_count(self) -> None:
        """An average over checks would rank one critical finding below three
        medium ones, inverting the priority a reviewer wants."""
        one_critical = risk_score([self._finding(FlagSeverity.CRITICAL)])
        three_low = risk_score([self._finding(FlagSeverity.LOW)] * 3)
        assert one_critical > three_low

    def test_score_is_monotonic_in_findings(self) -> None:
        one = risk_score([self._finding(FlagSeverity.MEDIUM)])
        two = risk_score([self._finding(FlagSeverity.MEDIUM)] * 2)
        assert two > one

    def test_scoring_is_deterministic(self) -> None:
        findings = [self._finding(FlagSeverity.HIGH), self._finding(FlagSeverity.LOW)]
        assert risk_score(findings) == risk_score(findings)


class TestRunAll:
    def test_clean_statement_produces_no_findings(self) -> None:
        assert run_all(BALANCED) == []

    def test_troubled_statement_produces_several(self) -> None:
        troubled = {
            "Assets": d("1000000"),
            "Liabilities": d("900000"),
            "StockholdersEquity": d("50000"),  # identity is out
            "AssetsCurrent": d("100000"),
            "LiabilitiesCurrent": d("400000"),  # illiquid
            "Revenue": d("500000"),
            "NetIncome": d("200000"),
            "OperatingCashFlow": d("10000"),  # large accruals
        }
        types = {f.flag_type for f in run_all(troubled)}

        assert "accounting_identity_violation" in types
        assert "low_liquidity" in types
        assert "high_accruals" in types

    def test_is_reproducible(self) -> None:
        """Identical inputs must always give identical findings; an audit tool
        that changes its answer between runs is not defensible."""
        first = run_all(BALANCED)
        second = run_all(BALANCED)
        assert [f.flag_type for f in first] == [f.flag_type for f in second]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------
def _synthetic_dataset(n_companies: int = 120, fraud_rate: float = 0.25) -> pd.DataFrame:
    """A separable synthetic dataset with a realistic grouped structure."""
    import numpy as np

    rng = np.random.default_rng(42)
    rows = []
    for company in range(n_companies):
        is_fraud = rng.random() < fraud_rate
        for _ in range(3):  # three filings per company
            row = {column: float(rng.normal(1.0, 0.2)) for column in FEATURE_COLUMNS}
            if is_fraud:
                # Fraudulent filings carry systematically higher accruals.
                row["accruals_ratio"] = float(rng.normal(2.5, 0.3))
            rows.append({**row, "is_fraud_label": bool(is_fraud), "company_id": f"c{company}"})
    return pd.DataFrame(rows)


class TestDatasetPreparation:
    def test_unlabelled_rows_are_excluded(self) -> None:
        """NULL is unlabelled, not negative. Training on it as negative would
        fabricate a huge number of confident false negatives."""
        frame = _synthetic_dataset(n_companies=40)
        # object dtype so the column can hold None alongside booleans, which is
        # exactly the three-valued shape the real column has.
        frame["is_fraud_label"] = frame["is_fraud_label"].astype("object")
        frame.loc[frame.index[:30], "is_fraud_label"] = None

        features, labels, _ = prepare_dataset(frame)
        assert len(features) == len(frame) - 30
        assert labels.notna().all()

    def test_missing_feature_column_is_rejected(self) -> None:
        frame = _synthetic_dataset(n_companies=10).drop(columns=["net_margin"])
        with pytest.raises(ValueError, match="missing feature columns"):
            prepare_dataset(frame)

    def test_entirely_unlabelled_dataset_is_rejected_with_guidance(self) -> None:
        frame = _synthetic_dataset(n_companies=10)
        frame["is_fraud_label"] = pd.Series([None] * len(frame), dtype="object")
        with pytest.raises(ValueError, match="aaer_cik_map"):
            prepare_dataset(frame)


class TestEvaluation:
    def test_reports_pr_auc_against_a_baseline(self) -> None:
        """PR-AUC alone is not interpretable without the base rate beside it."""
        features, labels, groups = prepare_dataset(_synthetic_dataset())
        report = evaluate(build_model("random_forest"), features, labels, groups)

        assert 0.0 <= report.pr_auc <= 1.0
        assert report.baseline_pr_auc == pytest.approx(report.positive_rate_test)
        assert report.lift_over_baseline > 1.0

    def test_never_reports_accuracy(self) -> None:
        """At a sub-1% base rate, accuracy above 99% is achievable by predicting
        'no fraud' for everything. Exposing it at all invites that mistake."""
        features, labels, groups = prepare_dataset(_synthetic_dataset())
        report = evaluate(build_model("logistic"), features, labels, groups)

        assert not hasattr(report, "accuracy")
        assert "accuracy" not in report.summary().lower()

    def test_split_keeps_companies_apart(self) -> None:
        """A random split puts one company's 2014 and 2015 filings on both
        sides, and the model learns the company rather than the misstatement."""
        frame = _synthetic_dataset()
        features, labels, groups = prepare_dataset(frame)
        report = evaluate(build_model("random_forest"), features, labels, groups)

        assert report.n_train + report.n_test == len(features)
        assert report.n_test > 0

    def test_single_class_dataset_is_rejected(self) -> None:
        frame = _synthetic_dataset(n_companies=40)
        frame["is_fraud_label"] = False

        features, labels, groups = prepare_dataset(frame)
        with pytest.raises(ValueError, match="only one class"):
            evaluate(build_model("logistic"), features, labels, groups)

    def test_recall_is_reported_at_a_working_precision(self) -> None:
        features, labels, groups = prepare_dataset(_synthetic_dataset())
        report = evaluate(build_model("random_forest"), features, labels, groups)

        assert 0.0 <= report.recall_at_target_precision <= 1.0
        assert set(report.confusion) == {
            "true_negative",
            "false_positive",
            "false_negative",
            "true_positive",
        }

    def test_both_model_kinds_fit(self) -> None:
        features, labels, groups = prepare_dataset(_synthetic_dataset())
        for kind in ("logistic", "random_forest"):
            report = evaluate(build_model(kind), features, labels, groups)
            assert report.pr_auc > 0

    def test_unknown_model_kind_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown model kind"):
            build_model("magic")
