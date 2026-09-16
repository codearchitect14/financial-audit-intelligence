# Data Pipeline

Status: **planned (Phase 1)**. This document records the design and the constraints
discovered while planning it, so that implementation does not rediscover them.

## Datasets

| Dataset | Role | Notes |
|---|---|---|
| SEC DERA Financial Statement Data Sets | Primary structured data | Quarterly XBRL ZIPs |
| SEC AAER enforcement releases | Fraud ground truth | Supplies the `is_fraud_label` |
| UCI Audit Data | Fast prototyping classifier | Small, clean, already labelled |
| `amitkedia/Financial-Fraud-Dataset` | Filing text for LLM and search testing | 85 fraud / 85 matched non-fraud |
| EDGAR-CORPUS | Long-form filing text for embeddings | 10-K filings, 1993 to 2020 |

## Constraint: the SEC blocks unidentified clients

The SEC requires every automated request to send a `User-Agent` header carrying a real
contact address, and rate-limits to roughly 10 requests per second. Requests without it
are refused, and the failure is easy to misread as a network problem.

This is why `SEC_USER_AGENT` is a first-class setting with a documented format, and why
`SEC_REQUESTS_PER_SECOND` defaults to 8 rather than 10: the published limit is a
ceiling, not a target, and being throttled mid-ingest leaves partial state.

## Constraint: DERA has no transaction-level data

The project plan specifies "Benford's law digit analysis on transaction amounts". The
SEC DERA datasets contain **aggregated statement line items**, not transactions. There
are no transaction amounts to analyse.

Benford analysis is still valid, but the unit of analysis changes: the leading-digit
distribution is computed across the **line-item values within a filing cohort** (a
company across periods, or a sector across companies in one period), not across
transactions within a filing. A single filing has far too few values for the test to
carry any statistical weight, so the detector operates on cohorts and records the
cohort it used in `audit_flags.detail`.

If transaction-level data becomes available through tenant uploads, the same detector
applies unchanged at the finer granularity.

## Constraint: the fraud label is severely imbalanced

AAER-positive filings are well under 1% of the SEC corpus. A classifier that always
predicts "no fraud" therefore scores above 99% accuracy while being completely useless.

The plan does not mention this, and it is the single most likely way for the modelling
work to produce a number that looks excellent and means nothing. Phase 3 therefore:

- reports **PR-AUC and recall at a fixed precision**, never accuracy;
- treats `NULL` labels as *unlabelled*, not as negative (see
  [data-model.md](data-model.md));
- splits **by company and by time**, never randomly. A random split puts one company's
  2014 and 2015 filings on both sides of the split, and the model learns the company
  rather than the fraud.

## Identifier matching

AAER releases name companies in prose; DERA identifies them by CIK. The merge is
therefore fuzzy and cannot be fully automated at acceptable precision.

The approach is a reviewed mapping table (`data/manifests/aaer_cik_map.csv`, tracked in
git) produced by name normalisation plus manual review, with every automatic match
recorded alongside its confidence. A mislabelled row is worse than an unlabelled one:
it teaches the model the opposite of the truth.

The enforcement **window** matters as much as the company. A company named in an AAER
is not fraudulent in every year it filed; only filings inside the violation period
carry a positive label. Filings outside it are labelled negative, and filings from
companies never named remain `NULL`.

## Idempotency

`uq_statement_accession (company_id, source_accession)` means ingestion can be
re-run over the same quarter without creating duplicates. Ingestion is expected to be
interrupted and resumed; it is written as an upsert, not an insert.
