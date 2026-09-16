#!/usr/bin/env python
"""Run the anomaly detection engine over ingested statements.

No LLM is involved at any point. Every flag this produces is the output of a
deterministic rule and is reproducible from the same inputs.

Examples
--------
Score everything::

    python scripts/analyze.py

Score a sample, and run the per-company Benford test::

    python scripts/analyze.py --limit 500 --benford
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

from fai.core.logging import configure_logging, get_logger  # noqa: E402
from fai.db.session import sync_session  # noqa: E402
from fai.detection.scoring import score_benford_by_company, score_statements  # noqa: E402

log = get_logger("analyze")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score ingested statements and write audit flags.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Score at most this many statements."
    )
    parser.add_argument(
        "--benford",
        action="store_true",
        help="Also run the per-company Benford leading-digit test.",
    )
    args = parser.parse_args()

    configure_logging(json_output=False)

    with sync_session() as session:
        result = score_statements(session, limit=args.limit)
        log.info("scoring_finished", summary=str(result))

        if args.benford:
            flagged = score_benford_by_company(session)
            log.info("benford_finished", flags_written=flagged)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
