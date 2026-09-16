/**
 * Top-level error boundary.
 *
 * React unmounts the whole tree when a render throws, so without a boundary a
 * single component bug produces a blank white page with no explanation. This
 * catches that and gives the user a way out.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // In a deployed environment this is where an error reporter would be
    // called. The console is the honest fallback: swallowing it silently would
    // make the bug invisible to whoever has to fix it.
    console.error("Unhandled render error", error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-50 px-4">
        <div className="w-full max-w-md rounded-xl bg-white p-8 text-center shadow-sm ring-1 ring-ink-200">
          <h1 className="text-xl font-bold text-ink-900">Something went wrong</h1>
          <p className="mt-2 text-sm text-ink-600">
            The page failed to render. Your data is unaffected; this is an interface fault.
          </p>

          {import.meta.env.DEV && (
            // Development only. The message can carry internals that should
            // never reach a user in a deployed environment.
            <pre className="mt-4 overflow-x-auto rounded-lg bg-ink-900 p-3 text-left text-xs text-ink-100">
              {error.message}
            </pre>
          )}

          <button
            type="button"
            onClick={() => {
              // A full reload rather than clearing state: the tree is already
              // in an unknown condition and a partial recovery can hide the
              // fault rather than fixing it.
              window.location.assign("/");
            }}
            className="mt-6 inline-flex rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-700"
          >
            Reload the application
          </button>
        </div>
      </div>
    );
  }
}
