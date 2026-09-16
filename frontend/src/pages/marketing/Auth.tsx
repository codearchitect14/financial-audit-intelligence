/**
 * Login and registration pages.
 *
 * Both are deliberately plain. An auth form is the one screen where a user
 * needs no discovery and every moment of ambiguity costs a session.
 */

import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { Alert, Button } from "@/components/ui";
import { Logo } from "@/components/marketing/Chrome";
import { useAuth } from "@/store/auth";

// Mirrors the backend rule in schemas/auth.py. Length only: composition rules
// measurably push people toward predictable patterns, and current NIST guidance
// advises against them.
const MIN_PASSWORD_LENGTH = 12;

function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <div className="flex w-full flex-col justify-center px-4 py-12 sm:px-6 lg:w-1/2 lg:px-16">
        <div className="mx-auto w-full max-w-md">
          <Logo />
          <h1 className="mt-8 text-2xl font-bold tracking-tight text-ink-900">{title}</h1>
          <p className="mt-2 text-sm text-ink-500">{subtitle}</p>
          <div className="mt-8">{children}</div>
          <p className="mt-6 text-sm text-ink-500">{footer}</p>
        </div>
      </div>

      {/* Decorative panel, hidden from assistive technology: it carries no
          information a screen reader user would be missing. */}
      <div
        className="hidden bg-ink-900 lg:flex lg:w-1/2 lg:flex-col lg:justify-center lg:px-16"
        aria-hidden="true"
      >
        <blockquote className="max-w-lg">
          <p className="text-2xl font-semibold leading-snug text-white">
            Statistics decide what is worth looking at. The model only explains what they found.
          </p>
          <footer className="mt-6 text-sm text-ink-400">
            Every finding in Ledgerline is reproducible from the same inputs.
          </footer>
        </blockquote>
      </div>
    </div>
  );
}

function useAuthError() {
  const [error, setError] = useState<string | null>(null);

  const capture = (exception: unknown) => {
    if (exception instanceof ApiError) {
      setError(exception.message);
      return;
    }
    // A network failure has no server message, and "Failed to fetch" tells a
    // user nothing actionable.
    setError("Could not reach the server. Check your connection and try again.");
  };

  return { error, setError, capture };
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const login = useAuth((state) => state.login);
  const { error, setError, capture } = useAuthError();
  const [submitting, setSubmitting] = useState(false);

  // Return the user to wherever the route guard interrupted them, rather than
  // dropping everyone on the dashboard.
  const redirectTo =
    (location.state as { from?: string } | null)?.from ?? "/app/dashboard";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    const data = new FormData(event.currentTarget);
    try {
      await login(String(data.get("email")), String(data.get("password")));
      navigate(redirectTo, { replace: true });
    } catch (exception) {
      capture(exception);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell
      title="Log in"
      subtitle="Access your organization's analysis."
      footer={
        <>
          No account yet?{" "}
          <Link to="/register" className="font-medium text-brand-600 hover:underline">
            Create one
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {error && <Alert tone="error">{error}</Alert>}

        <Field
          label="Work email"
          name="email"
          type="email"
          autoComplete="username"
          required
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />

        <Button type="submit" loading={submitting} className="w-full" size="lg">
          Log in
        </Button>
      </form>
    </AuthShell>
  );
}

export function RegisterPage() {
  const navigate = useNavigate();
  const register = useAuth((state) => state.register);
  const { error, setError, capture } = useAuthError();
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const data = new FormData(event.currentTarget);
    const password = String(data.get("password"));

    // Checked here as well as on the server, so the user learns the rule before
    // a round trip rather than after one.
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }

    setSubmitting(true);
    try {
      await register({
        email: String(data.get("email")),
        password,
        full_name: String(data.get("full_name")),
        organization_name: String(data.get("organization_name")),
      });
      navigate("/app/dashboard", { replace: true });
    } catch (exception) {
      capture(exception);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell
      title="Create your organization"
      subtitle="You will be its first administrator."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-brand-600 hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {error && <Alert tone="error">{error}</Alert>}

        <Field label="Full name" name="full_name" autoComplete="name" required />
        <Field label="Work email" name="email" type="email" autoComplete="username" required />
        <Field label="Organization name" name="organization_name" autoComplete="organization" required />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters. A memorable phrase beats a short, complicated one.`}
        />

        <Button type="submit" loading={submitting} className="w-full" size="lg">
          Create account
        </Button>
      </form>
    </AuthShell>
  );
}

function Field({
  label,
  name,
  hint,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string; name: string; hint?: string }) {
  const hintId = hint ? `${name}-hint` : undefined;
  return (
    <div>
      <label htmlFor={name} className="block text-sm font-medium text-ink-800">
        {label}
      </label>
      <input
        {...props}
        id={name}
        name={name}
        aria-describedby={hintId}
        className="mt-1 block w-full rounded-lg border-0 px-3 py-2 text-ink-900 ring-1 ring-inset ring-ink-300 placeholder:text-ink-400 focus:ring-2 focus:ring-inset focus:ring-brand-600"
      />
      {hint && (
        <p id={hintId} className="mt-1 text-xs text-ink-500">
          {hint}
        </p>
      )}
    </div>
  );
}
