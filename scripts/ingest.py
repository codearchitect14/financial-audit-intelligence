#!/usr/bin/env python
"""Ingest SEC DERA quarterly financial statement data.

Examples
--------
Ingest a single quarter::

    python scripts/ingest.py 2023q1

Ingest several, and point at a local archive directory::

    python scripts/ingest.py 2023q1 2023q2 --data-dir ./data

Ingest an archive already on disk, without contacting the SEC::

    python scripts/ingest.py --archive ./data/sec_dera/2023q1.zip

Before the first run, set SEC_USER_AGENT in backend/.env to a real contact
address. The SEC refuses requests that do not identify the client.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this file directly from a checkout without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

from fai.core.logging import configure_logging, get_logger  # noqa: E402
from fai.ingestion.aaer import load_aaer_mapping  # noqa: E402
from fai.ingestion.pipeline import (  # noqa: E402
    DEFAULT_AAER_MAPPING,
    Quarter,
    ingest_archive,
    ingest_quarters,
)

log = get_logger("ingest")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest SEC DERA financial statement data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "quarters",
        nargs="*",
        help="Quarters to ingest, for example 2023q1 2023q2.",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="Ingest a local archive directly instead of downloading.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Directory for downloaded archives (default: DATA_DIR from the environment).",
    )
    parser.add_argument(
        "--aaer-mapping",
        type=Path,
        default=DEFAULT_AAER_MAPPING,
        help="Reviewed AAER-to-CIK mapping CSV used to apply fraud labels.",
    )
    args = parser.parse_args()

    if not args.quarters and not args.archive:
        parser.error("give at least one quarter, or --archive")

    configure_logging(json_output=False)

    if args.archive:
        if not args.archive.exists():
            log.error("archive_not_found", path=str(args.archive))
            return 1
        result = ingest_archive(args.archive, load_aaer_mapping(args.aaer_mapping))
    else:
        try:
            quarters = [Quarter.parse(q) for q in args.quarters]
        except ValueError as exc:
            parser.error(str(exc))
        result = ingest_quarters(
            quarters, data_dir=args.data_dir, aaer_mapping=args.aaer_mapping
        )

    log.info("ingest_finished", summary=str(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
