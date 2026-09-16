"""Fraud label merge from SEC Accounting and Auditing Enforcement Releases.

An AAER names a company found to have misstated its financials and gives the
period the misstatement covers. That period is the whole point: a company named
in an enforcement release was not fraudulent in every year it ever filed, and
labelling all of its filings positive is the single most effective way to train
a model that has learned nothing.

Labelling rules
---------------
``True``
    The filing's period falls inside a matched enforcement window.

``False``
    The company appears in the mapping table, but this filing's period falls
    outside every enforcement window for it.

``NULL``
    The company does not appear in the mapping table at all. This is
    *unlabelled*, which is emphatically not the same as "not fraud": the SEC
    prosecutes a small fraction of what occurs, so an unprosecuted company is
    simply unknown. Treating NULL as negative would fabricate a vast number of
    confident false negatives.

Matching
--------
AAER releases identify companies in prose; DERA identifies them by CIK. The join
is therefore made through a reviewed mapping file rather than by fuzzy name
matching at ingest time, because a mislabelled row is worse than an unlabelled
one: it teaches the model the opposite of the truth.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from fai.core.logging import get_logger

log = get_logger(__name__)

MAPPING_COLUMNS = {
    "cik",
    "company_name",
    "violation_start",
    "violation_end",
    "aaer_number",
    "match_confidence",
}

# Rows below this confidence are treated as unreviewed and ignored. A weak
# name match that silently becomes a training label is exactly the failure this
# threshold exists to prevent.
MIN_CONFIDENCE = 0.90


@dataclass(frozen=True)
class EnforcementWindow:
    """One enforcement action against one company, over one period."""

    cik: str
    company_name: str
    violation_start: date
    violation_end: date
    aaer_number: str
    match_confidence: float

    def covers(self, period_end: date) -> bool:
        return self.violation_start <= period_end <= self.violation_end


class AaerLabelIndex:
    """Windows grouped by CIK, for labelling filings."""

    def __init__(self, windows: list[EnforcementWindow]):
        self._by_cik: dict[str, list[EnforcementWindow]] = {}
        for window in windows:
            self._by_cik.setdefault(window.cik, []).append(window)

    def __len__(self) -> int:
        return sum(len(windows) for windows in self._by_cik.values())

    @property
    def company_count(self) -> int:
        return len(self._by_cik)

    def label(self, cik: str, period_end: date | None) -> bool | None:
        """Return the three-valued label for a filing.

        ``None`` when the company is unknown, or when the filing has no period
        end date to compare against, since a window cannot be evaluated without
        one.
        """
        windows = self._by_cik.get(cik)
        if windows is None:
            return None
        if period_end is None:
            return None
        return any(window.covers(period_end) for window in windows)


def _parse_date(raw: str, *, field: str, line: int) -> date:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"line {line}: {field} must be YYYY-MM-DD, got {raw!r}") from exc


def load_aaer_mapping(path: Path) -> AaerLabelIndex:
    """Load the reviewed AAER-to-CIK mapping table.

    The file is tracked in git because it is hand-reviewed and cannot be
    regenerated. See docs/data-pipeline.md.
    """
    if not path.exists():
        log.warning("aaer_mapping_absent", path=str(path))
        return AaerLabelIndex([])

    windows: list[EnforcementWindow] = []
    skipped_low_confidence = 0

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = MAPPING_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required columns: {sorted(missing)}")

        for line, row in enumerate(reader, start=2):
            confidence = float(row["match_confidence"])
            if confidence < MIN_CONFIDENCE:
                skipped_low_confidence += 1
                continue

            start = _parse_date(row["violation_start"], field="violation_start", line=line)
            end = _parse_date(row["violation_end"], field="violation_end", line=line)
            if end < start:
                raise ValueError(f"line {line}: violation_end precedes violation_start")

            windows.append(
                EnforcementWindow(
                    cik=row["cik"].strip().zfill(10),
                    company_name=row["company_name"].strip(),
                    violation_start=start,
                    violation_end=end,
                    aaer_number=row["aaer_number"].strip(),
                    match_confidence=confidence,
                )
            )

    index = AaerLabelIndex(windows)
    log.info(
        "aaer_mapping_loaded",
        windows=len(index),
        companies=index.company_count,
        skipped_low_confidence=skipped_low_confidence,
    )
    return index
