# Data Model

The schema is defined in `backend/src/fai/db/models/` and created by migration `0001`.
This document records the decisions behind it, particularly the ones that differ from
the original project plan and the ones that are easy to get wrong.

## Tenancy

Every tenant-owned table carries an `organization_id`.

On the two **reference-data** tables, `companies` and `financial_statements`, the
column is **nullable**, and `NULL` means "public reference data". This is how the
ingested SEC corpus is stored: one shared copy, readable by every tenant, writable by
none of them. A non-NULL value marks a row that is private to that organization.

Consequently:

- Queries against reference tables filter `organization_id IN (:caller_org, NULL)`.
- Queries against private tables (`documents`, `audit_reports`, `document_chunks`)
  filter `organization_id = :caller_org`.

The alternative, copying the SEC corpus per tenant, was rejected: it multiplies storage
and embedding cost by the tenant count for data that is identical and already public.

### Deviation from the plan

Section 7 of the project plan defined `organizations` but gave `users` no
`organization_id`, and gave none to `companies`, `financial_statements`,
`financial_line_items`, or `audit_flags`, while section 8 required role-based
multi-user access. As specified, every tenant would have seen every row. Tenant
scoping had to be present in migration `0001`; retrofitting it later would require
backfilling ownership for rows whose owner is no longer knowable.

## Tables

| Table | Purpose | Tenancy |
|---|---|---|
| `organizations` | Tenant root | n/a |
| `users` | Authenticated principal | `organization_id` NOT NULL |
| `refresh_tokens` | Revocable server-side sessions | via `user_id` |
| `activity_log` | Append-only audit trail | nullable, `ON DELETE SET NULL` |
| `companies` | Reporting entity | nullable = public |
| `financial_statements` | One filing, one period | nullable = public |
| `financial_line_items` | Tagged values within a statement | via `statement_id` |
| `audit_flags` | Deterministic findings | via `statement_id` |
| `documents` | Uploaded files | `organization_id` NOT NULL |
| `document_chunks` | Passages plus embeddings | denormalised `organization_id` |
| `llm_usage_log` | Per-call metering | nullable |
| `llm_response_cache` | Response deduplication | not scoped, see below |
| `audit_reports` | Generated reports | `organization_id` NOT NULL |

`refresh_tokens` and `activity_log` were required by sections 8 and 9 of the plan but
absent from its schema list; both are included here.

## Decisions worth knowing

### Money is `Numeric`, never `Float`

`financial_line_items.value` is `Numeric(28, 4)`. These figures reach the hundreds of
billions, are compared for exact accounting identities (assets equals liabilities plus
equity), and feed Benford digit analysis, which reads the leading digit of the decimal
representation. Binary floating point would introduce drift that silently corrupts all
three, and the corruption would be invisible in ordinary review.

### Primary keys are UUIDs

Identifiers appear in URLs and exported reports. A sequential integer would leak row
counts and let one tenant enumerate another tenant's resources by guessing.

### Enums are checked `VARCHAR`, not native Postgres enums

Adding a value to a native `ENUM` requires `ALTER TYPE`, which complicates
transactional migrations and rollbacks. A `VARCHAR` with a `CHECK` constraint has the
same integrity guarantee and evolves with an ordinary constraint swap.

### Timestamps use `func.now()`, never the string `"now()"`

Declaring `server_default="now()"` makes SQLAlchemy emit the value as a *literal*,
which Postgres coerces into a frozen constant:

```sql
created_at timestamptz DEFAULT '2026-09-16 10:13:40+00'::timestamp with time zone
```

Every row inserted afterwards carries the migration's timestamp rather than its own
insert time. On `activity_log` this silently destroys the audit trail while still
looking correct in review.

This bug was present in the first draft of the schema and was caught by `alembic
check`. It is now guarded by an explicit test,
`tests/test_schema_integration.py::TestTimestampDefaults`, which asserts that no
timestamp column in the database has a literal default.

### Cascading deletes use `passive_deletes=True`

Foreign keys declare `ON DELETE CASCADE`, but SQLAlchemy's ORM default is to `UPDATE`
the child row's foreign key to `NULL` before deleting the parent. Against a `NOT NULL`
column that raises `NotNullViolation`, and it defeats the database-level guarantee even
where it succeeds. Every relationship whose foreign key cascades sets
`passive_deletes=True` so the database performs the cascade.

### Uniqueness constraints that make jobs re-runnable

- `uq_statement_accession (company_id, source_accession)` makes ingestion idempotent.
- `uq_flag_statement_type_method` makes the detection job idempotent.
- `uq_document_org_sha256` de-duplicates uploads by content, so re-uploading the same
  bytes reuses existing embeddings instead of paying to generate them again.
- `uq_companies_public_cik` is a **partial** unique index
  (`WHERE organization_id IS NULL`), so the public corpus cannot hold duplicate CIKs
  while private rows may reuse one freely.

### The LLM cache is deliberately not tenant-scoped

`llm_response_cache` is keyed by `(prompt_hash, task_type, model)`. Two tenants share
an entry only when their prompts were byte-identical, in which case the response
contains nothing the second tenant did not already supply. The model is part of the key
because the same prompt answered by the fallback model is a different response, and
serving one under the other would make results irreproducible.

### The fraud label is three-valued

`financial_statements.is_fraud_label` is nullable. `NULL` means *unlabelled*, which is
not the same as *not fraud*. Only a filing that falls inside a matched AAER enforcement
window is labelled `False`. Collapsing unlabelled into negative would fabricate
hundreds of thousands of false negatives and make any reported model accuracy
meaningless.

### Vector width is pinned to configuration

`document_chunks.embedding` is `vector(384)`, matching `BAAI/bge-small-en-v1.5`. The
width is read from `settings.embedding_dimensions`, and an integration test asserts
that the declared column width matches. Switching to a model of a different width
requires a migration and a full re-embed, not just a configuration change.

## Extensions

`vector` and `pgcrypto` are created in two places, deliberately:

- `infra/db/init/01_extensions.sql`, run once at container start as the bootstrap
  superuser, so the application role never needs superuser.
- Migration `0001`, because a managed provider such as Neon or Supabase never runs the
  container init script and would otherwise fail on the first vector column.

Both statements are idempotent. The downgrade does not drop them: they may be shared
with other schemas, and dropping the `vector` type cascades into every dependent
object.
