# AI Financial Reporting and Audit Intelligence Platform

An AI-assisted platform for financial reporting and audit intelligence. It ingests
financial statement data, applies statistical and machine-learning checks to detect
anomalies and risk, uses vector search to retrieve relevant context, and calls a large
language model only at the final step, to explain findings in plain language.

The system is designed to run entirely on free-tier infrastructure and free-tier LLM
APIs.

---

## Architecture

The single most important design rule is the order of operations:

```
  Ingest ──▶ Normalise ──▶ Detect (statistics + ML) ──▶ Retrieve (pgvector) ──▶ Explain (LLM)
   no LLM      no LLM            no LLM                       no LLM            LLM, batched
                                                                                 and cached
```

Every finding is produced by deterministic code. The LLM never decides *whether*
something is wrong; it only writes prose about findings that already exist. This has
three consequences that shape the whole codebase:

1. **Results are reproducible.** Re-running the detectors on the same data yields the
   same flags, which is a hard requirement for anything audit-facing.
2. **The token budget is bounded by the number of findings**, not the size of the
   dataset. A 500MB filing corpus costs the same in tokens as a small one.
3. **The platform degrades gracefully.** With no LLM key configured at all, ingestion,
   detection, scoring, and search still work. Only the narrative text is missing.

### Components

| Layer | Technology | Notes |
|---|---|---|
| API | FastAPI on Python 3.12 | async request path |
| Database | PostgreSQL 16 + pgvector | one database for relational and vector data |
| Migrations | Alembic | synchronous engine |
| Embeddings | `BAAI/bge-small-en-v1.5` via `fastembed` | ONNX Runtime, 384 dimensions |
| Detection | scikit-learn, pandas, numpy | no LLM involvement |
| LLM | Groq (`openai/gpt-oss-20b`), Gemini fallback | cached and metered |
| Frontend | React 18, Vite, TypeScript, Tailwind | marketing site plus dashboard |

---

## Quick start

Requirements: Docker, Python 3.12, and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Start Postgres with pgvector
docker compose -f infra/docker-compose.yml up -d db

# 2. Configure the backend
cd backend
cp .env.example .env

# 3. Install dependencies and apply the schema
uv sync --extra dev
uv run alembic upgrade head

# 4. Run
uv run uvicorn fai.main:app --reload
```

Then:

- API docs: <http://localhost:8000/docs>
- Liveness: <http://localhost:8000/api/v1/health>
- Readiness: <http://localhost:8000/api/v1/health/ready>

Readiness reports on the database and the pgvector extension individually, so a
`degraded` response tells you which dependency is missing.

> **Port note.** The stack binds Postgres to host port **5436**, not 5432, because
> 5432 is commonly already in use. Change `POSTGRES_PORT` in `infra/.env` and the
> matching `DATABASE_URL` in `backend/.env` if you want a different port.

---

## Running the checks

```bash
cd backend
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy src              # types (strict)
uv run pytest                # tests
uv run alembic check         # models and migrations agree
```

`pytest` runs without a database: tests that need one are marked `integration` and
skip themselves when none is reachable. Start the database to run the full suite.

---

## Environment variables

Every variable is documented in [`backend/.env.example`](backend/.env.example). The
ones that matter most:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | One DSN. The asyncpg and psycopg variants are derived from it, so the app and its migrations can never target different databases. |
| `JWT_SECRET_KEY` | Token signing key. The app **refuses to start in production** while this is the development default. |
| `CORS_ORIGINS` | Explicit origin allowlist. A wildcard is rejected in production. |
| `EMBEDDING_DIMENSIONS` | Must match the `vector(N)` column width. Changing it requires a migration and a full re-embed. |
| `SEC_USER_AGENT` | **Required before ingestion.** The SEC blocks requests that do not identify the client with a real contact address. |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | Optional. Without them the LLM layer serves cached results only. |

---

## Repository layout

```
backend/
  src/fai/
    core/        configuration, logging, error types
    db/          SQLAlchemy models, session management
    api/         FastAPI routers
  alembic/       migrations
  tests/         pytest suite
frontend/        React application (marketing site + dashboard)
infra/           docker-compose, Dockerfiles, database init
docs/            one document per subsystem
scripts/         data ingestion and batch jobs
```

---

## Documentation

| Document | Covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System design and the no-LLM-first rule |
| [docs/data-model.md](docs/data-model.md) | Schema, tenancy rules, and why each decision was made |
| [docs/data-pipeline.md](docs/data-pipeline.md) | Datasets, ingestion, and the fraud-label merge |
| [docs/llm-strategy.md](docs/llm-strategy.md) | Token minimisation, caching, provider failover |
| [docs/development.md](docs/development.md) | Local setup, conventions, troubleshooting |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branching, commits, review expectations |

Interactive API documentation is generated by FastAPI at `/docs` and is disabled in
production.

---

## Project status

| Phase | Scope | Status |
|---|---|---|
| 0 | Project setup, schema, CI, containerisation | **Complete** |
| 1 | Data pipeline (SEC DERA, UCI, AAER merge) | Not started |
| 2 | Core backend APIs and authentication | Not started |
| 3 | Anomaly detection engine | Not started |
| 4 | Embeddings and semantic search | Not started |
| 5 | LLM integration layer | Not started |
| 6 | Risk scoring and report generation | Not started |
| 7 | Frontend | Not started |
| 8 | Security hardening and full test coverage | Not started |
| 9 | Deployment | Not started |

Phase 0 delivers the full 13-table schema, a verified reversible migration, the
application skeleton with structured logging and a consistent error envelope, a
containerised Postgres with pgvector, and a CI pipeline running lint, strict type
checking, tests, migration-drift detection, dependency auditing, and secret scanning.
