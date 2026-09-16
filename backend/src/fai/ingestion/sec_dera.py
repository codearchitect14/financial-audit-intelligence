"""Parser for the SEC DERA Financial Statement Data Sets.

Each quarterly archive is a ZIP containing four tab-separated files. Two matter
here:

``sub.txt``
    One row per submission: accession number, CIK, registrant name, SIC code,
    form type, fiscal year and period, period end date, filing date.

``num.txt``
    One row per reported numeric fact: accession number, XBRL tag, the date the
    fact refers to, the number of quarters it spans, unit of measure, and the
    value. This file is the large one, routinely several hundred megabytes
    uncompressed for a single quarter.

Two DERA conventions drive the whole parser and are easy to get wrong:

``qtrs``
    The span a fact covers. ``0`` is an instant (balance-sheet figures), ``1``
    is one quarter, ``4`` is a full year. Reading a ``qtrs=4`` revenue against a
    ``qtrs=0`` balance produces a ratio that is silently meaningless.

``ddate``
    The date the fact refers to, which is **not** necessarily the submission's
    period. A single filing restates prior periods, so ``num.txt`` carries
    several years of history for each tag. Filtering to the submission's own
    period is what separates the current figures from the comparatives.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from fai.core.logging import get_logger
from fai.db.models.enums import FilingType, FiscalPeriod, StatementSection
from fai.ingestion.tags import WANTED_TAGS, concept_for_tag, tag_preference

log = get_logger(__name__)

# Forms carrying full financial statements. Everything else in a DERA archive
# (8-K, S-1, proxy material) is out of scope for statement-level analysis.
SUPPORTED_FORMS: dict[str, FilingType] = {
    "10-K": FilingType.ANNUAL_10K,
    "10-Q": FilingType.QUARTERLY_10Q,
    "10-K/A": FilingType.AMENDED_10KA,
    "10-Q/A": FilingType.AMENDED_10QA,
}

FISCAL_PERIODS: dict[str, FiscalPeriod] = {
    "FY": FiscalPeriod.FY,
    "Q1": FiscalPeriod.Q1,
    "Q2": FiscalPeriod.Q2,
    "Q3": FiscalPeriod.Q3,
    "Q4": FiscalPeriod.Q4,
}

# num.txt is read in pieces so that a several-hundred-megabyte file never has to
# fit in memory at once. Free-tier instances have little of it to spare.
NUM_CHUNK_ROWS = 250_000


@dataclass(frozen=True)
class ParsedSubmission:
    """One filing, normalised from a ``sub.txt`` row."""

    accession: str
    cik: str
    company_name: str
    sic_code: str | None
    country: str | None
    filing_type: FilingType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    period_end_date: date | None
    filed_date: date | None


@dataclass(frozen=True)
class ParsedFact:
    """One numeric fact belonging to a submission."""

    accession: str
    tag: str
    concept: str
    section: StatementSection
    value: Decimal
    unit: str


def _parse_dera_date(raw: object) -> date | None:
    """Parse a DERA ``YYYYMMDD`` integer date.

    Missing and malformed dates are common in the corpus and are not worth
    failing an entire archive over, so they become ``None``.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip().split(".")[0]
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _normalise_cik(raw: object) -> str:
    """Zero-pad a CIK to the canonical ten digits.

    DERA stores the CIK as an integer, dropping leading zeros; EDGAR URLs and
    every other SEC source use the padded form. Normalising at the boundary is
    what lets the AAER label merge join on it later.
    """
    text = str(raw).strip().split(".")[0]
    return text.zfill(10)


def parse_submissions(archive: Path) -> list[ParsedSubmission]:
    """Read and normalise ``sub.txt`` from a quarterly archive."""
    with zipfile.ZipFile(archive) as zf, zf.open("sub.txt") as handle:
        frame = pd.read_csv(
            handle,
            sep="\t",
            dtype=str,
            usecols=[
                "adsh",
                "cik",
                "name",
                "sic",
                "countryba",
                "form",
                "fy",
                "fp",
                "period",
                "filed",
            ],
            na_filter=False,
        )

    submissions: list[ParsedSubmission] = []
    skipped_form = 0
    skipped_period = 0

    for row in frame.itertuples(index=False):
        filing_type = SUPPORTED_FORMS.get(row.form)
        if filing_type is None:
            skipped_form += 1
            continue

        fiscal_period = FISCAL_PERIODS.get(row.fp)
        fiscal_year_raw = str(row.fy).strip()
        if fiscal_period is None or not fiscal_year_raw.isdigit():
            # Without a fiscal year and period the filing cannot be placed on a
            # timeline, which makes it useless for period-over-period analysis.
            skipped_period += 1
            continue

        submissions.append(
            ParsedSubmission(
                accession=row.adsh.strip(),
                cik=_normalise_cik(row.cik),
                company_name=row.name.strip(),
                sic_code=row.sic.strip() or None,
                country=(row.countryba.strip() or None),
                filing_type=filing_type,
                fiscal_year=int(fiscal_year_raw),
                fiscal_period=fiscal_period,
                period_end_date=_parse_dera_date(row.period),
                filed_date=_parse_dera_date(row.filed),
            )
        )

    log.info(
        "dera_submissions_parsed",
        archive=archive.name,
        kept=len(submissions),
        skipped_unsupported_form=skipped_form,
        skipped_missing_period=skipped_period,
    )
    return submissions


def _expected_qtrs(submission: ParsedSubmission, *, duration: bool) -> set[int]:
    """Which ``qtrs`` values are correct for this submission and concept type.

    Instant facts are always ``qtrs = 0``. Duration facts span the reporting
    period: four quarters for an annual filing, one for a quarterly filing.
    """
    if not duration:
        return {0}
    if submission.fiscal_period is FiscalPeriod.FY:
        return {4}
    return {1}


def parse_facts(
    archive: Path,
    submissions: dict[str, ParsedSubmission],
) -> Iterator[ParsedFact]:
    """Stream the relevant facts from ``num.txt``.

    Yields at most one fact per (submission, concept). Where a filing reports
    the same concept under several tags, the catalogue's preference order
    decides which one wins, so a filing carrying both ``Revenues`` and the
    ASC 606 revenue tag resolves to a single, consistent figure.
    """
    # (accession, concept) -> (preference rank, fact). Kept only for the
    # accessions present in this archive, which bounds memory by submission
    # count rather than by fact count.
    best: dict[tuple[str, str], tuple[int, ParsedFact]] = {}

    with zipfile.ZipFile(archive) as zf, zf.open("num.txt") as handle:
        reader = pd.read_csv(
            handle,
            sep="\t",
            dtype=str,
            usecols=["adsh", "tag", "ddate", "qtrs", "uom", "value"],
            na_filter=False,
            chunksize=NUM_CHUNK_ROWS,
        )

        for chunk in reader:
            # Cheap filters first: the tag allowlist removes the large
            # majority of rows before any per-row work happens.
            chunk = chunk[chunk["tag"].isin(WANTED_TAGS)]
            if chunk.empty:
                continue
            chunk = chunk[chunk["adsh"].isin(submissions.keys())]
            if chunk.empty:
                continue

            for row in chunk.itertuples(index=False):
                submission = submissions[row.adsh]
                concept = concept_for_tag(row.tag)
                if concept is None:
                    continue

                try:
                    qtrs = int(row.qtrs)
                except (TypeError, ValueError):
                    continue
                if qtrs not in _expected_qtrs(submission, duration=concept.duration):
                    continue

                # Discard the restated comparatives: only facts dated at the
                # submission's own period end describe the current filing.
                fact_date = _parse_dera_date(row.ddate)
                if (
                    submission.period_end_date is not None
                    and fact_date != submission.period_end_date
                ):
                    continue

                # Non-monetary units (shares, pure ratios) are out of scope;
                # mixing them into value analysis is meaningless.
                unit = (row.uom or "").strip().upper()
                if unit != "USD":
                    continue

                try:
                    value = Decimal(str(row.value).strip())
                except (InvalidOperation, ValueError):
                    continue

                key = (row.adsh, concept.name)
                rank = tag_preference(row.tag)
                existing = best.get(key)
                if existing is not None and existing[0] <= rank:
                    continue

                best[key] = (
                    rank,
                    ParsedFact(
                        accession=row.adsh,
                        tag=concept.name,
                        concept=concept.name,
                        section=concept.section,
                        value=value,
                        unit=unit,
                    ),
                )

    log.info("dera_facts_parsed", archive=archive.name, facts=len(best))
    for _, fact in best.values():
        yield fact
