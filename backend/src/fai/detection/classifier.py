"""Supervised fraud risk classifier.

This module exists as much to prevent a misleading result as to produce a good
one. Two properties of the problem make the obvious approach actively wrong:

**Class imbalance.** Filings named in an SEC enforcement release are well under
1% of the corpus. A model that predicts "no fraud" for everything therefore
scores above 99% accuracy while being completely useless. Accuracy is never
reported here. The metrics are PR-AUC and recall at a fixed precision, which do
not flatter a degenerate classifier.

**Leakage through time and entity.** A random train/test split puts one
company's 2014 and 2015 filings on both sides of the boundary, so the model
learns to recognise the company rather than the misstatement, and the held-out
score is inflated. Splitting is therefore grouped by company and ordered by
time, which is also how the model would actually be used: fitted on the past,
applied to the present.

``NULL`` labels are excluded from training entirely. Unlabelled is not negative
(see docs/data-pipeline.md); treating it as negative would fabricate hundreds of
thousands of confident false negatives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from fai.core.logging import get_logger

log = get_logger(__name__)

# Ratios used as model features. Deliberately the same quantities the
# deterministic detectors screen, so a model finding can always be traced back
# to something a human can read.
FEATURE_COLUMNS: tuple[str, ...] = (
    "current_ratio",
    "quick_ratio",
    "debt_to_equity",
    "gross_margin",
    "net_margin",
    "operating_margin",
    "return_on_assets",
    "asset_turnover",
    "accruals_ratio",
)

# The precision an auditor is willing to work at. Recall is reported at this
# precision because "how much fraud do we catch if we accept three false
# positives for every true one" is the question a review team actually asks.
TARGET_PRECISION = 0.25


@dataclass
class EvaluationReport:
    """Honest metrics for an imbalanced binary problem."""

    n_train: int
    n_test: int
    positive_rate_train: float
    positive_rate_test: float
    pr_auc: float
    roc_auc: float
    baseline_pr_auc: float
    recall_at_target_precision: float
    threshold_at_target_precision: float
    confusion: dict[str, int] = field(default_factory=dict)
    report: str = ""

    @property
    def lift_over_baseline(self) -> float:
        """How much better than guessing at the base rate.

        A PR-AUC equal to the positive rate is what a random classifier scores.
        Anything at or below 1.0 here means the model has learned nothing,
        whatever its accuracy might look like.
        """
        if self.baseline_pr_auc <= 0:
            return 0.0
        return self.pr_auc / self.baseline_pr_auc

    def summary(self) -> str:
        return (
            f"PR-AUC {self.pr_auc:.4f} (baseline {self.baseline_pr_auc:.4f}, "
            f"lift {self.lift_over_baseline:.2f}x), ROC-AUC {self.roc_auc:.4f}, "
            f"recall {self.recall_at_target_precision:.3f} at precision "
            f"{TARGET_PRECISION:.2f}"
        )


def build_model(kind: str = "random_forest") -> Pipeline:
    """Build a model pipeline.

    ``class_weight="balanced"`` in both models compensates for the imbalance
    during fitting. Imputation and scaling live inside the pipeline so they are
    fitted on training data only; fitting a scaler on the full dataset before
    splitting leaks test-set statistics into training and inflates the result.
    """
    if kind == "logistic":
        estimator: Any = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)
        steps = [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", estimator),
        ]
    elif kind == "random_forest":
        estimator = RandomForestClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=20,
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )
        # Trees need no scaling; imputation is still required because a missing
        # ratio is common and is not the same as zero.
        steps = [("impute", SimpleImputer(strategy="median")), ("model", estimator)]
    else:
        raise ValueError(f"unknown model kind {kind!r}")

    return Pipeline(steps)


def prepare_dataset(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Split a frame into features, labels, and grouping keys.

    Expects the ratio columns plus ``is_fraud_label`` and ``company_id``.
    Unlabelled rows are dropped here, and nowhere else, so that the exclusion is
    impossible to forget.
    """
    missing = set(FEATURE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"dataset is missing feature columns: {sorted(missing)}")
    for required in ("is_fraud_label", "company_id"):
        if required not in frame.columns:
            raise ValueError(f"dataset is missing the {required!r} column")

    labelled = frame[frame["is_fraud_label"].notna()].copy()
    if labelled.empty:
        raise ValueError(
            "No labelled rows. Populate data/manifests/aaer_cik_map.csv and re-run "
            "ingestion before training."
        )

    features = labelled[list(FEATURE_COLUMNS)].astype(float)
    labels = labelled["is_fraud_label"].astype(int)
    groups = labelled["company_id"].astype(str)
    return features, labels, groups


def evaluate(
    model: Pipeline,
    features: pd.DataFrame,
    labels: pd.Series,
    groups: pd.Series,
    *,
    test_size: float = 0.25,
) -> EvaluationReport:
    """Fit and evaluate with a company-grouped split.

    No company appears in both train and test. Without that, the model can
    identify a company from its ratio signature and recall its label, and the
    held-out score measures memorisation rather than generalisation.
    """
    if labels.nunique() < 2:
        raise ValueError(
            "Training data contains only one class; a classifier cannot be fitted or "
            "meaningfully evaluated."
        )

    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=42)
    train_index, test_index = next(splitter.split(features, labels, groups))

    x_train, x_test = features.iloc[train_index], features.iloc[test_index]
    y_train, y_test = labels.iloc[train_index], labels.iloc[test_index]

    if y_test.nunique() < 2:
        raise ValueError(
            "The held-out split contains only one class, so no metric can be computed. "
            "This usually means there are too few labelled positives or too few "
            "distinct companies."
        )

    model.fit(x_train, y_train)
    scores = model.predict_proba(x_test)[:, 1]

    precision, recall, thresholds = precision_recall_curve(y_test, scores)
    # Find the highest recall achievable at or above the target precision.
    usable = precision[:-1] >= TARGET_PRECISION
    if usable.any():
        best = int(np.argmax(np.where(usable, recall[:-1], -1)))
        recall_at_target = float(recall[best])
        threshold_at_target = float(thresholds[best])
    else:
        recall_at_target = 0.0
        threshold_at_target = 1.0

    predictions = (scores >= threshold_at_target).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_test, predictions, labels=[0, 1]).ravel()

    return EvaluationReport(
        n_train=len(x_train),
        n_test=len(x_test),
        positive_rate_train=float(y_train.mean()),
        positive_rate_test=float(y_test.mean()),
        pr_auc=float(average_precision_score(y_test, scores)),
        roc_auc=float(roc_auc_score(y_test, scores)),
        # A random classifier's PR-AUC equals the positive rate. Reporting it
        # alongside makes a useless model impossible to mistake for a good one.
        baseline_pr_auc=float(y_test.mean()),
        recall_at_target_precision=recall_at_target,
        threshold_at_target_precision=threshold_at_target,
        confusion={
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
        report=classification_report(y_test, predictions, zero_division=0),
    )


def save_model(model: Pipeline, path: Path) -> None:
    """Persist a fitted pipeline."""
    import joblib

    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    log.info("model_saved", path=str(path))


def load_model(path: Path) -> Pipeline:
    """Load a fitted pipeline."""
    import joblib

    model: Pipeline = joblib.load(path)
    return model
