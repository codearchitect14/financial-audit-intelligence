# AI Financial Reporting and Audit Intelligence Platform

## Project Plan

---

## 1. Project Overview

An AI assisted platform for financial reporting and audit intelligence. The platform ingests financial statement data, applies statistical and machine learning checks to detect anomalies and risk, uses vector search to retrieve relevant context, and uses large language models only at the final step to explain findings and generate reports in plain language.

The system is built to run on free tier infrastructure and free tier LLM APIs, with a strict token minimization design so that a full analysis cycle uses the smallest possible number of LLM calls and tokens.

Target users: internal auditors, external audit firms, financial controllers, compliance teams.

---

## 2. Problem Statement

Financial statement review and audit work is largely manual. Reviewers must:

- Read large volumes of financial statements and transaction data
- Manually spot inconsistencies, outliers, and non-compliant entries
- Cross check figures against accounting standards
- Write audit summaries and risk notes by hand

This is slow, expensive, and error prone. Existing audit software is either fully manual (spreadsheets) or fully black box (no explanation of flags). There is no accessible platform that combines statistical detection, semantic retrieval, and AI generated explanation in one workflow that a mid sized firm can afford and understand.

---

## 3. Goals and Non-Goals

**Goals**

- Ingest financial statement and audit datasets into a normalized database
- Detect anomalies using statistics and machine learning before touching any LLM
- Provide semantic search over filings and audit notes using vector embeddings
- Use LLMs only to explain already flagged items and to draft reports, minimizing token usage
- Provide a secure, role based, multi user web application
- Provide a professional marketing landing page describing the product, with a login entry point to the application

**Non-Goals (first release)**

- Real time transaction monitoring
- Direct ERP system integrations (SAP, Oracle) beyond file upload
- Regulatory certification or legal audit sign-off automation

---

## 4. Tech Stack (all free and open source or free tier)

| Layer | Technology |
|---|---|
| Backend language | Python 3.11+ |
| Backend framework | FastAPI |
| ORM / migrations | SQLAlchemy 2.0, Alembic |
| Database | PostgreSQL 16 with pgvector extension |
| Embeddings model | Open source Hugging Face model, `BAAI/bge-small-en-v1.5` (or `sentence-transformers/all-MiniLM-L6-v2` as a lighter alternative) |
| Anomaly detection / ML | scikit-learn, pandas, numpy |
| LLM provider 1 | Groq API, model `openai/gpt-oss-20b` |
| LLM provider 2 | Google Gemini API, model `gemini-2.5-flash-lite` (fallback `gemini-2.5-flash`) |
| Background jobs | APScheduler (simple) or Celery with Redis (if scale requires) |
| File storage | Local disk volume, or MinIO (open source S3-compatible) |
| Auth | OAuth2 password flow with JWT access and refresh tokens, `passlib[argon2]` for hashing |
| Frontend framework | React 18 with Vite, TypeScript |
| Styling | Tailwind CSS, shadcn/ui component library |
| Charts | Recharts |
| State / data fetching | React Query, Zustand |
| Routing | React Router |
| Containerization | Docker, docker-compose |
| CI/CD | GitHub Actions (free tier) |
| Testing (backend) | pytest, pytest-asyncio, httpx |
| Testing (frontend) | Vitest, React Testing Library, Playwright |
| Hosting (free tier options) | Render or Railway for backend, Vercel or Netlify for frontend, Neon or Supabase for managed PostgreSQL with pgvector |
| Documentation | Markdown, README.md, docs folder |

---

## 5. LLM Strategy and Token Minimization

The platform must run within free tier LLM limits. The design below ensures the LLM is the last and smallest step in any workflow, not the first.

**Provider abstraction**

Build a single internal interface, for example `llm_client.generate(prompt, max_tokens, task_type)`, with two backends:

- Primary: Groq, model `openai/gpt-oss-20b`
- Secondary (fallback): Gemini, model `gemini-2.5-flash-lite`

The client tracks daily and per minute usage locally in the database (a `llm_usage_log` table) and automatically switches to the secondary provider when the primary provider returns a rate limit error or when the tracked usage approaches the known free tier ceiling. Both providers are called through their official REST APIs with API keys stored as environment variables, never hardcoded.

**Steps that must never call an LLM**

- Data ingestion and normalization
- Ratio calculations (liquidity, leverage, margin ratios)
- Statistical anomaly detection (z-score, isolation forest, Benford's law digit analysis on transaction amounts)
- Embedding generation (handled by the local Hugging Face model, not the LLM)
- Vector similarity search (handled by pgvector)

**Steps that may call an LLM, and how usage is minimized**

- Explaining a flagged anomaly: only flagged items are sent, not the full dataset. Multiple flagged items from the same document are batched into a single prompt with a numbered list, producing one LLM call instead of many.
- Natural language query answering: the user question is converted to an embedding, matched against pgvector, and only the top retrieved rows (typically 5 to 10) are included in the prompt, not raw tables.
- Report drafting: the report is assembled from already computed numbers and already generated explanations; the LLM is asked only to write connecting narrative text, with a strict output token cap.

**Prompt design rules**

- All prompts request structured JSON output with a fixed schema, to avoid long free-form responses
- `max_tokens` is capped per task type (short explanation: 150 to 250 tokens, report section: 400 to 600 tokens)
- Every LLM response is cached in Postgres keyed by a hash of the input prompt and task type, so an identical request is never sent twice
- System prompts are short and reused, and where the provider supports prompt caching (Groq supports this) the same system prompt text is kept identical across calls to benefit from cached input pricing

---

## 6. Dataset

Since no proprietary data is available, the platform is built and tested on the following free, publicly available, and directly relevant datasets.

### 6.1 SEC Financial Statement Data Sets (primary structured data)

- Source: U.S. Securities and Exchange Commission, Division of Economic and Risk Analysis (DERA)
- Content: quarterly XBRL structured financial statement data (balance sheet, income statement, cash flow) submitted by public companies
- Download: `https://www.sec.gov/dera/data/financial-statement-data-sets` (quarterly ZIP files, for example `2023q1.zip`)
- Reference code: `https://github.com/sec-gov/python-for-dera-financial-datasets`
- Usage in the project: this is the core financial statement dataset used to populate the reporting module, compute ratios, and run anomaly detection. Load using the provided Python examples, normalize into the `financial_statements` and `financial_line_items` tables described in section 8.

### 6.2 SEC Accounting and Auditing Enforcement Releases (AAER), fraud ground truth labels

- Source: SEC enforcement division
- Content: real enforcement cases naming companies found to have committed financial statement fraud, including violation period and accounting treatment involved
- Access: index at `https://www.sec.gov/divisions/enforce/friactions.htm`; for a ready to use structured version, use the academic dataset compiled by Bao et al. (commonly cited as the "Bao AAER dataset"), searchable on GitHub under "AAER fraud dataset"
- Usage in the project: provides the fraud/no fraud label used to validate and benchmark the anomaly detection and risk scoring models

### 6.3 UCI Audit Data (fast prototyping dataset)

- Source: UCI Machine Learning Repository, data collected from the Auditor Office of India
- Content: tabular audit risk data across sectors such as Irrigation, Public Health, Buildings and Roads, Forest, Corporate, and others, with a fraud/no fraud label
- Download: `https://archive.ics.uci.edu/dataset/475/audit+data`
- Usage in the project: small, clean, already labeled dataset used in Phase 3 to build and validate the first version of the risk classification model before the larger SEC data is fully integrated

### 6.4 Hugging Face Financial Fraud Dataset (text and LLM testing)

- Source: Hugging Face Datasets, `amitkedia/Financial-Fraud-Dataset`
- Content: SEC filings, including MD&A sections, for 85 companies involved in fraud cases and 85 matched non-fraud companies
- Download: `https://huggingface.co/datasets/amitkedia/Financial-Fraud-Dataset`
- Usage in the project: used to test the LLM explanation layer and the semantic search feature on real filing text

### 6.5 EDGAR-CORPUS (filing text for embeddings)

- Source: academic corpus of all 10-K filings submitted to the SEC between 1993 and 2020, extracted from EDGAR
- Access: search "EDGAR-CORPUS" on Hugging Face Datasets or GitHub for the packaged version
- Usage in the project: source of long-form filing text (MD&A, footnotes) used to generate embeddings for the semantic search and retrieval module

### 6.6 Dataset usage flow

1. Download SEC DERA quarterly files and the UCI Audit Data file
2. Run the ingestion scripts (Phase 1) to normalize both into the shared database schema
3. Merge AAER fraud labels onto the matching SEC filings by company identifier and fiscal period, to create a labeled training set
4. Use EDGAR-CORPUS and the Hugging Face fraud dataset text fields to generate embeddings for semantic search
5. Use the UCI Audit Data set for the earliest working version of the classifier, then retrain on the larger merged SEC and AAER data once the pipeline is stable

---

## 7. Database Schema (PostgreSQL with pgvector)

Core tables:

- `users` (id, email, hashed_password, full_name, role, is_active, created_at)
- `organizations` (id, name, created_at)
- `companies` (id, name, cik, sector, created_at)
- `financial_statements` (id, company_id, fiscal_year, fiscal_period, filing_type, source_dataset, created_at)
- `financial_line_items` (id, statement_id, tag, value, unit, created_at)
- `audit_flags` (id, statement_id, flag_type, severity, description, detection_method, created_at)
- `documents` (id, organization_id, uploaded_by, file_path, doc_type, created_at)
- `document_chunks` (id, document_id, chunk_text, embedding vector(384), created_at) — the `embedding` column uses the pgvector `vector` type
- `llm_usage_log` (id, provider, model, task_type, prompt_hash, tokens_used, created_at)
- `llm_response_cache` (id, prompt_hash, task_type, response_json, created_at)
- `audit_reports` (id, organization_id, statement_id, generated_by, content, created_at)

Role based access is enforced through the `role` field on `users` with values such as `admin`, `auditor`, `reviewer`, `viewer`.

---

## 8. Authentication and Authorization

- OAuth2 password flow implemented in FastAPI using `fastapi.security.OAuth2PasswordBearer`
- Passwords hashed with Argon2 through `passlib`
- Short lived JWT access token (15 to 30 minutes) and a longer lived refresh token (7 days), both signed with a secret key stored in an environment variable
- Refresh tokens stored server side (a `refresh_tokens` table) with the ability to revoke a session
- Role based authorization implemented as a FastAPI dependency that checks the current user's role against the required role for each endpoint
- All endpoints under `/api` require a valid access token except `/api/auth/login`, `/api/auth/register`, and `/api/health`

---

## 9. Data Security

- All traffic served over HTTPS in every environment beyond local development
- Environment variables and API keys managed with `.env` files locally and provider secret managers in deployment, never committed to source control
- Strict input validation on every endpoint using Pydantic models
- Parameterized queries only, through SQLAlchemy, to prevent SQL injection
- Rate limiting on authentication and LLM facing endpoints using `slowapi`
- CORS restricted to the deployed frontend origin only
- Audit logging: every create, update, and delete action is written to an `activity_log` table with user id, action, and timestamp
- Uploaded files scanned for type and size limits before storage
- Dependency vulnerability scanning with `pip-audit` and `npm audit` as part of CI
- Sensitive financial figures stored as-is (they are already public SEC data in this project), but the schema and code must be written so that field level encryption could be added later for private client data

---

## 10. Frontend Plan

The frontend has two parts: a public marketing website and an authenticated application dashboard.

### 10.1 Public marketing website

Must look like a professional enterprise software company website. Pages and sections:

- **Header**: logo, navigation (Product, Solutions, Security, Pricing, Resources), a clearly visible "Log In" button in the top right corner linking to `/login`, and a "Request Demo" call to action button
- **Hero section**: a strong headline describing the value proposition, a supporting subheadline, a primary call to action button, and a supporting product screenshot or illustration
- **Trust bar**: a row of neutral compliance and security badges (for example SOC 2 style badge placeholders, encryption badge, uptime badge) to convey enterprise credibility
- **Feature grid**: three to six feature cards, each with an icon, short title, and one sentence description (examples: automated risk scoring, semantic document search, AI generated audit narratives, real time anomaly flags)
- **How it works section**: a three or four step visual flow from data upload to report generation
- **Product screenshot / dashboard preview section**: a large visual mock of the actual dashboard with annotations
- **Security and compliance section**: a dedicated section explaining data handling, encryption, and access control, written in clear enterprise language
- **Case study or testimonial placeholders**: two or three quote style blocks with a name, title, and company placeholder, clearly marked as sample content in code comments so the developer replaces them with real content later
- **Footer**: company description, navigation columns (Product, Company, Legal, Contact), social links, and copyright line

Design guidance:

- Use a restrained color palette: one primary brand color, one accent color, neutral grays, white background
- Use a professional typeface such as Inter or IBM Plex Sans, loaded through Google Fonts
- Use high quality, license free imagery from sources such as Unsplash or generated illustrations, never placeholder gray boxes in the final build
- Fully responsive layout for desktop, tablet, and mobile
- Meet basic accessibility standards: sufficient color contrast, semantic HTML, alt text on all images, keyboard navigable menus

### 10.2 Authenticated application

- `/login` and `/register` pages
- `/dashboard`: summary cards (total statements analyzed, open flags, high risk companies, recent reports) and a trend chart
- `/statements`: table of ingested financial statements with filter and search
- `/statements/:id`: detail view showing line items, computed ratios, and audit flags with LLM generated explanations
- `/search`: natural language search box that queries the vector database and returns matching filing passages
- `/reports`: list of generated audit reports, with a "Generate Report" action
- `/settings`: user profile, organization members, role management (visible only to admin role)

---

## 11. Phase Wise Development Plan

### Phase 0: Project Setup

- Initialize monorepo with `backend/` and `frontend/` folders
- Set up Docker and docker-compose with services: `api`, `db` (Postgres with pgvector image), `frontend`
- Configure GitHub repository, branch protection, and GitHub Actions workflow skeleton
- Set up `.env.example` files for both backend and frontend
- Deliverable: a running "hello world" FastAPI endpoint and a running React app, both containerized

### Phase 1: Data Pipeline

- Write ingestion scripts to download and parse SEC DERA quarterly ZIP files
- Write a parser for the UCI Audit Data CSV
- Write a merge script to attach AAER fraud labels to matching SEC filings
- Normalize all of the above into the `companies`, `financial_statements`, and `financial_line_items` tables using SQLAlchemy models and Alembic migrations
- Deliverable: a repeatable command (for example `python scripts/ingest.py`) that populates the database from raw downloaded files

### Phase 2: Core Backend APIs

- Implement authentication endpoints (register, login, refresh, logout)
- Implement role based authorization dependency
- Implement CRUD endpoints for companies, statements, and organizations
- Implement file upload endpoint for user supplied documents, storing files and creating `documents` rows
- Deliverable: documented REST API covering auth and core data access, verified with automated tests

### Phase 3: Anomaly Detection Engine (no LLM)

- Compute standard financial ratios (current ratio, debt to equity, gross margin, net margin) from `financial_line_items`
- Implement statistical checks: z-score outlier detection on ratios, Benford's law digit distribution check on transaction level amounts where available
- Train a baseline classifier (logistic regression and a tree based model such as random forest) on the UCI Audit Data set, then retrain on the merged SEC and AAER data
- Write results into the `audit_flags` table with a severity score and detection method
- Deliverable: a batch job that scores every ingested statement and produces flags, with unit tested detection logic

### Phase 4: Embeddings and Semantic Search

- Set up the local Hugging Face embeddings model (`BAAI/bge-small-en-v1.5`) served through a small internal function or a lightweight FastAPI microservice
- Enable the pgvector extension in PostgreSQL and add the `embedding` column to `document_chunks`
- Write a chunking pipeline for long filing text (EDGAR-CORPUS, uploaded documents) into passages of a few hundred tokens
- Generate and store embeddings for all chunks
- Implement a similarity search endpoint using pgvector's cosine distance operator
- Deliverable: a working `/api/search` endpoint that returns the most relevant text passages for a natural language query, with no LLM call involved

### Phase 5: LLM Integration Layer

- Implement the provider abstraction described in section 5, with Groq as primary and Gemini as fallback
- Implement the `llm_usage_log` and `llm_response_cache` tables and the caching logic
- Implement the batched anomaly explanation prompt and the retrieval augmented question answering prompt
- Add automated fallback handling and clear logging when a provider switch happens
- Deliverable: a `/api/explain` endpoint that takes flagged item ids and returns cached or freshly generated explanations, and a `/api/ask` endpoint for natural language questions

### Phase 6: Audit Intelligence Features

- Implement risk scoring that combines the statistical flags from Phase 3 into a single per-statement risk score
- Implement report generation that assembles computed ratios, flags, and LLM generated narrative into a structured report, stored in `audit_reports`
- Add report export to PDF using an open source library such as `weasyprint`
- Deliverable: end to end flow from a selected statement to a downloadable audit report

### Phase 7: Frontend Build

- Build the marketing website described in section 10.1 as static React pages
- Build the authenticated dashboard pages described in section 10.2
- Connect all pages to the backend API using React Query
- Implement protected routes that redirect unauthenticated users to `/login`
- Deliverable: a fully navigable frontend covering both the marketing site and the application

### Phase 8: Security Hardening and Testing

- Write backend unit and integration tests covering auth, data pipeline, anomaly detection, and LLM layer with mocked provider responses
- Write frontend component tests and at least one end to end Playwright test covering login through report generation
- Run `pip-audit` and `npm audit`, fix any high severity findings
- Perform a manual review against the OWASP API Security Top 10 checklist
- Deliverable: passing CI pipeline with test coverage report

### Phase 9: Deployment

- Deploy PostgreSQL with pgvector using a free tier managed provider (Neon or Supabase)
- Deploy the backend to a free tier service (Render or Railway)
- Deploy the frontend to Vercel or Netlify
- Configure environment variables and secrets on each platform
- Set up basic uptime monitoring using a free tier tool
- Deliverable: a publicly reachable, working deployment of both the marketing site and the application

---

## 12. Documentation Requirements

The repository must include:

- A root `README.md` covering: project overview, architecture diagram, tech stack, setup instructions for local development, environment variable reference, how to run the data ingestion scripts, how to run tests, and how to deploy
- A `docs/` folder with one markdown file per major subsystem: data pipeline, anomaly detection, embeddings and search, LLM integration, authentication, and frontend
- Inline docstrings on all backend functions and modules
- An `API.md` or auto generated OpenAPI documentation (FastAPI provides this automatically at `/docs`) referenced from the README
- A `CONTRIBUTING.md` describing coding standards, branch naming, and pull request process

All documentation must be written in clear, professional, technical language suitable for a new developer joining the project with no prior context.

---

## 13. Risk Summary

| Risk | Mitigation |
|---|---|
| Free tier LLM rate limits exceeded during testing | Provider fallback (Groq to Gemini), response caching, batched prompts |
| Dataset mismatch between SEC identifiers and AAER labels | Manual mapping table for the initial merge, documented in Phase 1 |
| pgvector performance at scale | Use an approximate index (HNSW or IVFFlat) once chunk count grows beyond a few hundred thousand rows |
| Free tier hosting cold starts or downtime | Document the limitation clearly in the README and keep the option to move to paid tiers documented in the deployment section |
