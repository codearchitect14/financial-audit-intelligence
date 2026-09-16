/**
 * Search and question answering.
 *
 * Two deliberately separate actions, because they cost very different things:
 *
 * **Search** is vector retrieval only. It is free, instant, and spends no
 * model quota. It returns passages.
 *
 * **Ask** takes those passages and spends one model call to turn them into an
 * answer. The UI makes the distinction visible so a user chooses knowingly
 * rather than discovering the cost afterwards.
 */

import { type FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import { insights, search as searchApi } from "@/api/endpoints";
import { Alert, Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui";
import type { AskResponse, SearchResponse } from "@/api/types";

export default function SearchPage() {
  const [query, setQuery] = useState("");

  const search = useMutation<SearchResponse, ApiError, string>({
    mutationFn: (value) => searchApi.query({ q: value, limit: 10 }),
  });

  const ask = useMutation<AskResponse, ApiError, string>({
    mutationFn: (value) => insights.ask(value),
  });

  function handleSearch(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    ask.reset();
    search.mutate(query.trim());
  }

  return (
    <>
      <PageHeader
        title="Search"
        description="Semantic search over your indexed documents. Retrieval is free; asking for a written answer spends model quota."
      />

      <Card className="p-5">
        <form onSubmit={handleSearch} className="flex flex-col gap-3 sm:flex-row">
          <label htmlFor="search-query" className="sr-only">
            Search query
          </label>
          <input
            id="search-query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="How does the company recognise revenue?"
            maxLength={1000}
            className="flex-1 rounded-lg border-0 px-4 py-2.5 text-ink-900 ring-1 ring-inset ring-ink-300 placeholder:text-ink-400 focus:ring-2 focus:ring-inset focus:ring-brand-600"
          />
          <div className="flex gap-2">
            <Button type="submit" loading={search.isPending} disabled={!query.trim()}>
              Search passages
            </Button>
            <Button
              type="button"
              variant="secondary"
              loading={ask.isPending}
              disabled={!query.trim()}
              onClick={() => {
                search.reset();
                ask.mutate(query.trim());
              }}
            >
              Ask the model
            </Button>
          </div>
        </form>
        <p className="mt-2 text-xs text-ink-400">
          Search runs locally against the vector index and costs nothing. Ask sends the top
          passages to a language model.
        </p>
      </Card>

      {search.isError && (
        <div className="mt-6">
          <Alert tone="error" title="Search failed">
            {search.error.message}
          </Alert>
        </div>
      )}

      {ask.isError && (
        <div className="mt-6">
          <Alert tone="warning" title="Could not generate an answer">
            {ask.error.message} Passage search still works and costs nothing.
          </Alert>
        </div>
      )}

      {(search.isPending || ask.isPending) && (
        <div className="mt-6 space-y-3">
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} className="h-24" />
          ))}
        </div>
      )}

      {ask.isSuccess && (
        <section className="mt-6">
          <Card className="p-5">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-ink-900">Answer</h2>
              {ask.data.cached && (
                <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800 ring-1 ring-inset ring-emerald-200">
                  Cached, no quota used
                </span>
              )}
            </div>

            {!ask.data.sufficient_context && (
              <div className="mt-3">
                <Alert tone="warning">
                  The retrieved passages do not fully support an answer. Treat the text below
                  with corresponding caution.
                </Alert>
              </div>
            )}

            <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-ink-800">
              {ask.data.answer}
            </p>

            {ask.data.sources.length > 0 && (
              <div className="mt-5 border-t border-ink-200 pt-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Sources
                </h3>
                <ol className="mt-2 space-y-2">
                  {ask.data.sources.map((source) => (
                    <li key={source.index} className="text-xs text-ink-600">
                      <span
                        className={
                          ask.data.citations.includes(source.index)
                            ? "font-semibold text-brand-700"
                            : "text-ink-400"
                        }
                      >
                        [{source.index}]
                      </span>{" "}
                      <span className="font-medium text-ink-800">{source.document_name}</span>{" "}
                      <span className="text-ink-400">
                        (similarity {source.similarity.toFixed(3)})
                      </span>
                      <p className="mt-1 text-ink-500">{source.excerpt}</p>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </Card>
        </section>
      )}

      {search.isSuccess && (
        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold text-ink-900">
            {search.data.count} passage{search.data.count === 1 ? "" : "s"}
          </h2>

          {search.data.count === 0 ? (
            <EmptyState
              title="Nothing matched"
              description="No indexed passage was similar to that query. Upload documents and run the indexing job to build the vector index."
            />
          ) : (
            <div className="space-y-3">
              {search.data.results.map((result) => (
                <Card key={result.chunk_id} className="p-5">
                  <div className="flex items-center justify-between gap-3">
                    <p className="truncate text-sm font-medium text-ink-900">
                      {result.document_name}
                    </p>
                    <span className="shrink-0 rounded-md bg-ink-100 px-2 py-0.5 text-xs font-medium tabular-nums text-ink-600">
                      {result.similarity.toFixed(3)}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-ink-600">{result.text}</p>
                  <p className="mt-2 text-xs text-ink-400">Passage {result.chunk_index + 1}</p>
                </Card>
              ))}
            </div>
          )}
        </section>
      )}
    </>
  );
}
