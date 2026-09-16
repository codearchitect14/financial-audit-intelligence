"""Ingestion orchestration.

Ties the downloader, the parsers, the label index, and the loader into one
re-runnable operation over a list of quarters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fai.core.config import settings
from fai.core.logging import get_logger
from fai.db.session import sync_session
from fai.ingestion.aaer import AaerLabelIndex, load_aaer_mapping
from fai.ingestion.downloader import SecDownloader
from fai.ingestion.loader import (
    LoadResult,
    upsert_companies,
    upsert_facts,
    upsert_statements,
)
from fai.ingestion.sec_dera import parse_facts, parse_submissions

log = get_logger(__name__)

DEFAULT_AAER_MAPPING = Path("../data/manifests/aaer_cik_map.csv")


@dataclass
class Quarter:
    year: int
    quarter: int

    def __str__(self) -> str:
        return f"{self.year}Q{self.quarter}"

    @classmethod
    def parse(cls, text: str) -> Quarter:
        """Parse ``2023q1`` or ``2023Q1``."""
        cleaned = text.strip().lower()
        if "q" not in cleaned:
            raise ValueError(f"expected a quarter like 2023q1, got {text!r}")
        year_part, quarter_part = cleaned.split("q", 1)
        if not year_part.isdigit() or not quarter_part.isdigit():
            raise ValueError(f"expected a quarter like 2023q1, got {text!r}")
        quarter = int(quarter_part)
        if quarter not in (1, 2, 3, 4):
            raise ValueError(f"quarter must be 1-4, got {quarter}")
        return cls(int(year_part), quarter)


def ingest_archive(archive: Path, labels: AaerLabelIndex | None = None) -> LoadResult:
    """Ingest one DERA quarterly archive into the database."""
    submissions = parse_submissions(archive)
    if not submissions:
        log.warning("archive_had_no_usable_submissions", archive=archive.name)
        return LoadResult()

    by_accession = {s.accession: s for s in submissions}

    with sync_session() as session:
        company_ids, companies_created = upsert_companies(session, submissions)
        statement_ids, result = upsert_statements(session, submissions, company_ids, labels)
        result.companies_created = companies_created

        # Facts are streamed rather than materialised: num.txt does not fit
        # comfortably in memory on a free-tier instance.
        facts = list(parse_facts(archive, by_accession))
        result.line_items_written = upsert_facts(session, facts, statement_ids)

    log.info("archive_ingested", archive=archive.name, summary=str(result))
    return result


def ingest_quarters(
    quarters: list[Quarter],
    *,
    data_dir: Path | None = None,
    aaer_mapping: Path | None = None,
) -> LoadResult:
    """Download (if needed) and ingest each quarter in order."""
    root = data_dir or Path(settings.data_dir)
    labels = load_aaer_mapping(aaer_mapping or DEFAULT_AAER_MAPPING)
    downloader = SecDownloader()

    total = LoadResult()
    for quarter in quarters:
        archive = downloader.download_quarter(quarter.year, quarter.quarter, root)
        result = ingest_archive(archive, labels)
        total.companies_created += result.companies_created
        total.statements_created += result.statements_created
        total.statements_updated += result.statements_updated
        total.line_items_written += result.line_items_written
        total.labels_applied += result.labels_applied

    return total
