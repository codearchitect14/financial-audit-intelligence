"""Parser for the UCI Audit Data set.

A small, clean, already-labelled table of audit risk indicators collected by the
Auditor Office of India. It is used in Phase 3 to build and validate the first
version of the risk classifier before the much larger and messier SEC corpus is
fully merged.

It is deliberately *not* loaded into ``financial_statements``: its columns are
audit risk scores, not statement line items, and forcing them into that shape
would misrepresent both. It is read straight into a feature matrix.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fai.core.logging import get_logger

log = get_logger(__name__)

# The distributed archive contains two CSVs. audit_risk.csv carries the risk
# factor columns and the label; trial.csv is a partially overlapping variant.
# Only the first is used, to avoid duplicated rows under slightly different
# column names.
AUDIT_RISK_FILE = "audit_risk.csv"
LABEL_COLUMN = "Risk"


def load_uci_audit(path: Path) -> pd.DataFrame:
    """Load and clean the UCI audit risk table.

    Returns a frame whose last column is the binary ``Risk`` label and whose
    remaining columns are numeric features.
    """
    if path.is_dir():
        path = path / AUDIT_RISK_FILE
    frame = pd.read_csv(path)

    if LABEL_COLUMN not in frame.columns:
        raise ValueError(
            f"{path} has no '{LABEL_COLUMN}' column; this does not look like "
            "the UCI audit_risk.csv file."
        )

    # LOCATION_ID is a categorical identifier stored as text, and a handful of
    # rows carry non-numeric values such as 'LOHARU'. It is an identifier, not a
    # predictor, so it is dropped rather than encoded: keeping it would let the
    # model memorise which districts were audited.
    frame = frame.drop(columns=[c for c in ("LOCATION_ID",) if c in frame.columns])

    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    before = len(frame)
    # Money_Value has a small number of genuine nulls in the published data.
    # Median imputation, not row deletion: the set is only ~776 rows and
    # dropping them would discard real signal.
    features = [c for c in frame.columns if c != LABEL_COLUMN]
    frame[features] = frame[features].fillna(frame[features].median())
    frame = frame.dropna(subset=[LABEL_COLUMN])

    log.info(
        "uci_audit_loaded",
        rows=len(frame),
        dropped_missing_label=before - len(frame),
        features=len(features),
        positive_rate=round(float(frame[LABEL_COLUMN].mean()), 4),
    )
    return frame
