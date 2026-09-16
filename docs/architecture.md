# Architecture

## The ordering rule

```
  Ingest ──▶ Normalise ──▶ Detect ──▶ Retrieve ──▶ Explain
   no LLM      no LLM      no LLM     no LLM       LLM only
```

Deterministic code decides what is wrong. The LLM only writes prose about findings
that already exist in `audit_flags`. It is never asked to judge, score, or classify.

Three properties follow, and they are the reason the rule is not negotiable:

1. **Reproducibility.** Re-running detection on unchanged data produces identical
   flags. Anything audit-facing needs this; a sampled LLM cannot provide it.
2. **A bounded token budget.** Cost scales with the number of *findings*, not with the
   size of the dataset. Ingesting ten times more filings does not cost ten times more
   tokens.
3. **Graceful degradation.** With no LLM key configured, ingestion, detection, risk
   scoring, and semantic search all still work. Only narrative text is missing.

## Request path

```
Client
  │
  ├─ CORS (explicit origin allowlist)
  ├─ Request context middleware   assigns X-Request-ID, logs one structured line
  ├─ Router  /api/v1/...
  │    └─ Dependency: AsyncSession (rolled back on any exception)
  └─ Exception handlers           single JSON error envelope, no internal detail
```

Every error response has the same shape:

```json
{"error": {"code": "not_found", "message": "...", "details": {}}}
```

`message` is always safe to show a caller. Anything sensitive goes to the log, keyed by
the same request id the client received.

## Two database engines, one DSN

- **async (asyncpg)** drives the FastAPI request path, where the work is IO bound and
  concurrency matters.
- **sync (psycopg 3)** drives Alembic and the batch ingestion and scoring jobs, which
  are pandas- and scikit-learn-driven and have no reason to be asynchronous.

Both are derived from a single `DATABASE_URL`, so a deployment configures one value and
the application and its migrations cannot drift onto different databases.

## Embeddings run on ONNX, not torch

The plan specified `sentence-transformers`, which pulls in torch at roughly 800MB
installed. Free-tier hosting gives the API instance about 512MB of memory, so that
install cannot run there at all.

`fastembed` executes the same `BAAI/bge-small-en-v1.5` weights through ONNX Runtime at
roughly a tenth of the footprint, with the same 384-dimension output. The schema is
unaffected; only the runtime changes.

## Failure posture

| Dependency unavailable | Behaviour |
|---|---|
| Database | `/health` still returns 200; `/health/ready` returns 503 naming the failed check |
| pgvector extension | readiness reports `missing`; search is unavailable, everything else works |
| Groq | automatic failover to Gemini, recorded in `llm_usage_log` with `was_fallback` |
| Both LLM providers | cached explanations still served; new ones deferred, flags unaffected |

Liveness deliberately touches no dependency. A health check that queries Postgres takes
every instance out of rotation during a brief database blip, converting a degraded
service into an outage.

## Start-up guard

In production the application refuses to boot if the JWT signing key is still the
development default, if debug mode is on, or if the CORS allowlist contains a wildcard.
A forgotten signing key makes every token the service issues forgeable; that is not a
warning-level problem, so the process exits rather than serving traffic.
