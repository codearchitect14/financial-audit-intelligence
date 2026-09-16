# LLM Strategy

Status: **planned (Phase 5)**. The tables it depends on (`llm_usage_log`,
`llm_response_cache`) exist as of Phase 0.

## The budget

Free-tier quotas are measured in requests per minute and per day. The design target is
that a full analysis cycle over a statement costs **one** LLM call, and that repeating
it costs **zero**.

Four mechanisms, in the order they take effect:

1. **Nothing reaches the LLM that deterministic code can answer.** Ingestion,
   normalisation, ratio computation, statistical detection, embedding generation, and
   vector search never call it.
2. **Batching.** All flagged items on a statement go into one prompt as a numbered
   list, producing one call rather than one per finding.
3. **Caching.** Every response is stored keyed by
   `(prompt_hash, task_type, model)`. An identical request is never sent twice.
4. **Output caps.** `max_tokens` is capped per task type: 150 to 250 for a short
   explanation, 400 to 600 for a report section. Responses are requested as structured
   JSON against a fixed schema, which also prevents the model from rambling.

## What is sent

Only the contents of `audit_flags.detail`: the observed value, the expected range, the
detection method, and the identifying tag. Never the raw dataset, never full line-item
tables, never the filing text.

For retrieval-augmented answering, only the top 5 to 10 chunks returned by pgvector are
included, not the tables they came from.

## Provider failover

Primary is Groq (`openai/gpt-oss-20b`); fallback is Gemini
(`gemini-2.5-flash-lite`, then `gemini-2.5-flash`).

The client consults `llm_usage_log` before each call and switches to the fallback when
the primary returns a rate-limit error or when tracked usage approaches the known
free-tier ceiling. Failed and rate-limited calls are logged too: a provider that starts
refusing requests is precisely the signal the failover logic reads, and discarding
those rows would hide it.

Every fallback call is recorded with `was_fallback = true`, so the failover rate is
measurable rather than guessed at.

## Why the cache key includes the model

The same prompt answered by the fallback model is a different response. Serving one
under the other would make results irreproducible, which for an audit tool is a
correctness problem rather than an inconvenience.

## Why the cache is not tenant-scoped

Entries are shared across tenants because the key is a hash of the **full** prompt
text. Two tenants collide only when their prompts were byte-identical, in which case
the cached response contains nothing the second tenant did not itself supply. Prompts
built from public SEC data therefore share a cache entry, which is exactly the desired
behaviour; prompts containing private figures differ and do not collide.

## Prompt handling and safety

Retrieved chunks and uploaded document text are **data, never instructions**. A filing
can contain text that reads like a directive, and the platform must treat it as content
to be analysed. System prompts are kept short, identical across calls (which also lets
Groq's prompt caching apply), and state explicitly that retrieved passages are
untrusted input.

The prompt text itself is never written to `llm_usage_log`; only its hash is. That
table is read for operational dashboards and must not become a second copy of tenant
financial data.

## Degradation

With no API key configured, the LLM layer serves cached responses and otherwise
returns "explanation unavailable". Detection, scoring, search, and reporting continue
to work: the findings are produced by deterministic code and do not depend on prose
being available.
