# Security

A record of what is implemented, why, and what is deliberately not yet covered.

The honest summary: the controls below are architectural rather than
configuration, and each is tested. The gaps in section 4 are real and are listed
because an undocumented gap is worse than a documented one.

---

## 1. Review against the OWASP API Security Top 10

| Risk | Status | Where |
|---|---|---|
| **API1 Broken object level authorization** | Addressed | Every query is scoped in `repositories/finance.py`, never in a handler. A resource from another tenant does not resolve, returning 404 rather than 403. Tested in `test_statements_api.py::TestTenantIsolation`. |
| **API2 Broken authentication** | Addressed | Argon2id passwords, short-lived access tokens, revocable refresh sessions stored as SHA-256 hashes, single-use rotation with family revocation on replay. Token type is verified, so a refresh token cannot be presented as an access token. Tested in `test_auth.py`. |
| **API3 Broken object property level authorization** | Addressed | Responses are explicit Pydantic models. No endpoint serialises an ORM object directly, so a column added to a model cannot leak into a response by accident. |
| **API4 Unrestricted resource consumption** | Addressed | Page size capped at 200. Uploads capped and enforced while streaming, not from `Content-Length`. Rate limits on credential, upload, and quota-bearing endpoints. LLM calls metered against a daily ceiling checked before dispatch. |
| **API5 Broken function level authorization** | Addressed | Ordered role hierarchy with named capabilities in `core/permissions.py`, failing closed on an unrecognised role or capability. Enforced server-side; the frontend only hides controls. |
| **API6 Unrestricted access to sensitive business flows** | Partial | Report generation and explanation are rate limited and role gated. There is no per-organization quota, so one tenant can consume the shared model budget. See section 4. |
| **API7 Server side request forgery** | Addressed | The only outbound requests are to hard-coded provider hosts and the SEC domain. No user input reaches a URL. |
| **API8 Security misconfiguration** | Addressed | Production start-up fails on a default signing key, debug mode, or a CORS wildcard. Interactive docs disabled in production. Security headers on every response. Container runs unprivileged. Tested in `test_health.py` and `test_security_headers.py`. |
| **API9 Improper inventory management** | Addressed | One versioned prefix, `/api/v1`. OpenAPI generated from the code, so it cannot describe an endpoint that does not exist. |
| **API10 Unsafe consumption of third-party APIs** | Addressed | Provider responses are parsed strictly; malformed JSON is rejected rather than salvaged. Retrieved document text is fenced and declared as data, never instructions. Provider errors are truncated before logging. |

---

## 2. Data handling

**What reaches a language model.** Only the contents of `audit_flags.detail`
(observed value, expected range, detection method) and the top retrieved
passages. Never the raw dataset, never full line-item tables, never anything the
caller did not already have access to.

**What is logged.** `llm_usage_log` stores a prompt *hash*, never the prompt.
That table is read for operational dashboards and must not become a second copy
of tenant financial data. Provider error text is truncated to 512 characters.

**Passwords and tokens.** Passwords are Argon2id. Refresh tokens are stored as
SHA-256 hashes, so a database disclosure does not hand out usable sessions. The
access token is never persisted anywhere, on the server or in the browser.

**In the browser.** The access token lives in a module variable, not
`localStorage`. A token in `localStorage` turns a single XSS into a stolen
session that outlives the tab. The refresh token is persisted deliberately, so a
reload does not log the user out; it is the weaker of the two to persist because
it is revocable server-side and single-use. Asserted by
`src/test/client.test.ts` and by an end-to-end test against a real browser.

**Audit trail.** `activity_log` is append-only. `user_id` uses
`ON DELETE SET NULL`, so deleting a user cannot erase the record of what that
user did.

---

## 3. Upload handling

Upload is the most exposed write path: payload, filename, and declared type are
all attacker-controlled.

- **The stored path is generated, never derived from the upload.** A filename
  like `../../../.env` cannot influence where bytes land. The original name is
  kept in a column for display only.
- **Size is enforced while streaming.** A client can lie about
  `Content-Length`, or send a chunked body with none.
- **Type is checked against an allowlist and verified against magic bytes.** A
  declared `Content-Type` is a claim, not evidence.
- **Content is hashed and de-duplicated per tenant**, so identical bytes are
  never embedded twice.
- **Rejected uploads leave nothing behind.** Files are written under a temporary
  name and renamed only on success.

Tested in `test_documents.py`, including traversal payloads in seven forms.

---

## 4. Known gaps

Listed because they are real, not because they are acceptable.

| Gap | Impact | What it would take |
|---|---|---|
| No per-organization LLM quota | One tenant can exhaust the shared daily model budget | A per-org counter alongside the global one in `llm/client.py` |
| No virus scanning on uploads | A malicious file can be stored and later downloaded | ClamAV in the ingestion path, or an object-storage scanning hook |
| Rate limit state is in-process | Scaling beyond one instance multiplies the effective limit by the instance count | Set `RATE_LIMIT_STORAGE_URI` to a shared Redis |
| No account lockout | Rate limiting slows online guessing but does not stop a distributed attempt | Progressive delays keyed on the account, not just the address |
| No MFA | A stolen password is sufficient to authenticate | TOTP enrolment against the existing user model |
| PDF text extraction not implemented | PDFs upload and store but index as zero chunks | A parser, with its own security review; PDF parsers are a recurring CVE source |
| Financial figures not encrypted at rest | Relies on the provider's disk encryption | The schema is written so field-level encryption could be added; see docs/data-model.md |
| `X-Forwarded-For` is trusted for the first entry | A spoofed header can shift a rate-limit bucket | Correct only behind exactly one trusted proxy. It is used for logging and limiting, never for an authorization decision |

---

## 5. What CI enforces

- `pip-audit` against the resolved lockfile, strict.
- `npm audit` against production dependencies at high severity.
- Gitleaks over full history, so a secret committed and later removed is still
  caught.
- Strict `mypy` and `ruff`, which catch a surprising share of the input-handling
  mistakes that become vulnerabilities.
- The full test suite, including the tenant isolation, upload, auth, rate
  limiting, and security header modules.

---

## 6. Reporting a vulnerability

This is a demonstration deployment. Before it processes real client data it
needs, at minimum: the gaps in section 4 closed or accepted in writing, a
penetration test, a privacy notice reviewed by counsel replacing the placeholder
at `/privacy`, and a documented incident response process.
