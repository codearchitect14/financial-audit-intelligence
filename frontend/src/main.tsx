/**
 * Application entry point.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import { ApiError } from "./api/client";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A minute of freshness. Financial data changes on an ingestion schedule,
      // not continuously, so refetching more often is pure cost.
      staleTime: 60_000,
      // Refocusing a tab should not re-issue every query on the page.
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Never retry a request the server has already answered definitively.
        // Retrying a 401 races the token refresh, and retrying a 403 or 404
        // cannot succeed however many times it is attempted.
        if (error instanceof ApiError) {
          if (error.status >= 400 && error.status < 500) return false;
        }
        return failureCount < 2;
      },
    },
    mutations: {
      // Mutations are never retried automatically. A retried upload or report
      // generation would duplicate work and, for LLM calls, spend quota twice.
      retry: false,
    },
  },
});

const container = document.getElementById("root");
if (!container) throw new Error("Root element #root is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
