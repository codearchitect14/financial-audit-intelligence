# Data

This directory holds downloaded corpora and generated artifacts. Its contents are
**not tracked in git**: the datasets are large and reproducible, and the ingestion
scripts fetch them on demand.

Two exceptions are tracked, because they are hand-reviewed inputs that cannot be
regenerated:

- `manifests/` — dataset manifests and the AAER-to-CIK mapping table.
- This README.

See [docs/data-pipeline.md](../docs/data-pipeline.md) for the datasets and how they
are ingested.
