/**
 * Settings: profile, organization, and role management.
 *
 * Role management is admin-only, and the sidebar hides this page from
 * non-admins. That is a courtesy, not a control: the server enforces the rule
 * independently, and this page still renders a clear refusal if reached
 * directly.
 */

import { useQuery } from "@tanstack/react-query";

import { insights } from "@/api/endpoints";
import { Alert, Card, PageHeader } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import { hasRole, useAuth } from "@/store/auth";

const ROLE_DESCRIPTIONS: Array<{ role: string; summary: string }> = [
  { role: "admin", summary: "Manages the organization, its members, and their roles." },
  { role: "auditor", summary: "Uploads documents, runs analysis, and generates reports." },
  { role: "reviewer", summary: "Triages findings: acknowledge, resolve, or dismiss." },
  { role: "viewer", summary: "Read-only access to statements, findings, and reports." },
];

export default function SettingsPage() {
  const user = useAuth((state) => state.user);
  const isAdmin = hasRole(user, "admin");

  const budget = useQuery({
    queryKey: ["llm-budget"],
    queryFn: insights.budget,
  });

  return (
    <>
      <PageHeader title="Settings" description="Your profile, your organization, and quota." />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-ink-900">Profile</h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Name</dt>
              <dd className="font-medium text-ink-900">{user?.full_name}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Email</dt>
              <dd className="truncate font-medium text-ink-900">{user?.email}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Role</dt>
              <dd className="font-medium capitalize text-ink-900">{user?.role}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Last login</dt>
              <dd className="font-medium text-ink-900">
                {formatDateTime(user?.last_login_at ?? null)}
              </dd>
            </div>
          </dl>
        </Card>

        <Card className="p-5">
          <h2 className="text-sm font-semibold text-ink-900">Model quota</h2>
          {budget.isLoading ? (
            <p className="mt-4 text-sm text-ink-500">Loading...</p>
          ) : budget.isError ? (
            <p className="mt-4 text-sm text-ink-500">Quota status is unavailable.</p>
          ) : !budget.data?.providers_configured ? (
            <div className="mt-4">
              <Alert tone="info">
                No language model is configured. Detection, scoring, search, and reports all
                work; only generated narrative is unavailable.
              </Alert>
            </div>
          ) : (
            <>
              <dl className="mt-4 space-y-3 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-ink-500">Calls in the last 24 hours</dt>
                  <dd className="font-medium tabular-nums text-ink-900">
                    {budget.data.calls_today}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-ink-500">Daily ceiling</dt>
                  <dd className="font-medium tabular-nums text-ink-900">
                    {budget.data.ceiling}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-ink-500">Remaining</dt>
                  <dd className="font-medium tabular-nums text-ink-900">
                    {budget.data.remaining}
                  </dd>
                </div>
              </dl>
              <div
                className="mt-4 h-2 overflow-hidden rounded-full bg-ink-200"
                role="progressbar"
                aria-valuenow={budget.data.calls_today}
                aria-valuemin={0}
                aria-valuemax={budget.data.ceiling}
                aria-label="Daily model quota used"
              >
                <div
                  className={budget.data.exhausted ? "h-full bg-severity-high" : "h-full bg-brand-600"}
                  style={{
                    width: `${Math.min(100, (budget.data.calls_today / Math.max(1, budget.data.ceiling)) * 100)}%`,
                  }}
                />
              </div>
              <p className="mt-2 text-xs text-ink-400">
                A rolling 24-hour window. Responses are cached, so repeating a request costs
                nothing.
              </p>
            </>
          )}
        </Card>
      </div>

      <Card className="mt-6 p-5">
        <h2 className="text-sm font-semibold text-ink-900">Roles</h2>
        <p className="mt-1 text-xs text-ink-500">
          Roles are ordered: each one includes everything below it.
        </p>
        <dl className="mt-4 divide-y divide-ink-200">
          {ROLE_DESCRIPTIONS.map((entry) => (
            <div key={entry.role} className="flex gap-4 py-3">
              <dt className="w-24 shrink-0 text-sm font-medium capitalize text-ink-900">
                {entry.role}
                {user?.role === entry.role && (
                  <span className="ml-1 text-xs font-normal text-brand-600">(you)</span>
                )}
              </dt>
              <dd className="text-sm text-ink-600">{entry.summary}</dd>
            </div>
          ))}
        </dl>
      </Card>

      {!isAdmin && (
        <div className="mt-6">
          <Alert tone="info" title="Member management is admin-only">
            Ask an administrator in your organization to change a role. The server enforces
            this regardless of what the interface shows.
          </Alert>
        </div>
      )}
    </>
  );
}
