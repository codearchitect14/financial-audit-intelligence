#!/usr/bin/env python
"""Chunk and embed uploaded documents for semantic search.

Runs the local ONNX embedding model. No LLM API is called and no network access
is required beyond the one-time model download.

Examples
--------
Index everything pending::

    python scripts/index_documents.py

Index a bounded batch::

    python scripts/index_documents.py --limit 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

from fai.core.logging import configure_logging, get_logger  # noqa: E402
from fai.db.session import sync_session  # noqa: E402
from fai.search.service import index_pending_documents  # noqa: E402

log = get_logger("index")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Embed uploaded documents into the vector index.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum documents to process."
    )
    args = parser.parse_args()

    configure_logging(json_output=False)

    with sync_session() as session:
        chunks = index_pending_documents(session, limit=args.limit)

    log.info("indexing_finished", chunks_written=chunks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
