/**
 * Statement list and detail.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { flags as flagsApi, insights, reports, statements } from "@/api/endpoints";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  PageHeader,
  RiskBadge,
  SeverityBadge,
  Skeleton,
  StatusBadge,
} from "@/components/ui";
import { formatDate, formatMoney, formatPercent, formatRatio, humanise } from "@/lib/format";
import { hasRole, useAuth } from "@/store/auth";
import type { FlagStatus, RatioSet } from "@/api/types";

const PAGE_SIZE = 25;

export function StatementsList() {
  const [offset, setOffset] = useState(0);
  const [openOnly, setOpenOnly] = useState(false);
  const [minRisk, setMinRisk] = useState<number | undefined>(undefined);

  const query = useQuery({
    queryKey: ["statements", { offset, openOnly, minRisk }],
    queryFn: () =>
      statements.list({
        limit: PAGE_SIZE,
        offset,
        has_open_flags: openOnly || undefined,
        min_risk_score: minRisk,
      }),
  });

  const total = query.data?.total ?? 0;

  return (
    <>
      <PageHeader
        title="Statements"
        description="Filed statements, ordered by risk score. Unscored statements sort last rather than as though they were zero risk."
      />

      <Card className="mb-4 flex flex-wrap items-center gap-4 p-4">
        <label className="flex items-center gap-2 text-sm text-ink-700">
          <input
            type="checkbox"
            checked={openOnly}
            onChange={(event) => {
              setOpenOnly(event.target.checked);
              setOffset(0);
            }}
            className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-600"
          />
          Open findings only
        </label>

        <label className="flex items-center gap-2 text-sm text-ink-700">
          Minimum risk
          <select
            value={minRisk ?? ""}
            onChange={(event) => {
              setMinRisk(event.target.value ? Number(event.target.value) : undefined);
              setOffset(0);
            }}
            className="rounded-lg border-0 py-1.5 pl-3 pr-8 text-sm ring-1 ring-inset ring-ink-300 focus:ring-2 focus:ring-brand-600"
          >
            <option value="">Any</option>
            <option value="40">40 (elevated)</option>
            <option value="70">70 (high)</option>
          </select>
        </label>

        <span className="ml-auto text-sm text-ink-500">
          {total.toLocaleString()} statement{total === 1 ? "" : "s"}
        </span>
      </Card>

      {query.isError && (
        <Alert tone="error" title="Could not load statements">
          {(query.error as ApiError)?.message ?? "Unexpected error."}
        </Alert>
      )}

      <Card className="overflow-hidden">
        {query.isLoading ? (
          <div className="space-y-2 p-5">
            {Array.from({ length: 6 }, (_, index) => (
              <Skeleton key={index} className="h-12" />
            ))}
          </div>
        ) : total === 0 ? (
          <div className="p-6">
            <EmptyState
              title="No statements match"
              description="Adjust the filters, or ingest a quarter of SEC filings to populate the corpus."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Financial statements ordered by risk score</caption>
              <thead className="bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
                <tr>
                  <th scope="col" className="px-5 py-3 font-semibold">Company</th>
                  <th scope="col" className="px-5 py-3 font-semibold">Period</th>
                  <th scope="col" className="px-5 py-3 font-semibold">Filing</th>
                  <th scope="col" className="px-5 py-3 font-semibold">Period end</th>
                  <th scope="col" className="px-5 py-3 font-semibold">Risk</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-200">
                {query.data?.items.map((statement) => (
                  <tr key={statement.id} className="transition hover:bg-ink-50">
                    <td className="px-5 py-3">
                      <Link
                        to={`/app/statements/${statement.id}`}
                        className="font-medium text-brand-700 hover:underline"
                      >
                        {statement.company_name ?? "Unknown company"}
                      </Link>
                    </td>
                    <td className="px-5 py-3 text-ink-600">
                      FY{statement.fiscal_year} {statement.fiscal_period}
                    </td>
                    <td className="px-5 py-3 text-ink-600">{statement.filing_type}</td>
                    <td className="px-5 py-3 text-ink-600">
                      {formatDate(statement.period_end_date)}
                    </td>
                    <td className="px-5 py-3">
                      <RiskBadge score={statement.risk_score} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {total > PAGE_SIZE && (
        <nav className="mt-4 flex items-center justify-between" aria-label="Pagination">
          <Button
            variant="secondary"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </Button>
          <span className="text-sm text-ink-500">
            {offset + 1} to {Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </Button>
        </nav>
      )}
    </>
  );
}

const RATIO_LABELS: Array<{ key: keyof RatioSet; label: string; percent?: boolean }> = [
  { key: "current_ratio", label: "Current ratio" },
  { key: "quick_ratio", label: "Quick ratio" },
  { key: "debt_to_equity", label: "Debt to equity" },
  { key: "gross_margin", label: "Gross margin", percent: true },
  { key: "operating_margin", label: "Operating margin", percent: true },
  { key: "net_margin", label: "Net margin", percent: true },
  { key: "return_on_assets", label: "Return on assets", percent: true },
  { key: "asset_turnover", label: "Asset turnover" },
  { key: "accruals_ratio", label: "Accruals ratio", percent: true },
];

export function StatementDetail() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const user = useAuth((state) => state.user);
  const canRun = hasRole(user, "auditor");
  const canTriage = hasRole(user, "reviewer");

  const query = useQuery({
    queryKey: ["statement", id],
    queryFn: () => statements.get(id),
    enabled: Boolean(id),
  });

  const explain = useMutation({
    mutationFn: () => insights.explain(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["statement", id] }),
  });

  const generateReport = useMutation({
    mutationFn: () => reports.generate(id),
  });

  const triage = useMutation({
    mutationFn: ({ flagId, status }: { flagId: string; status: FlagStatus }) =>
      flagsApi.updateStatus(flagId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["statement", id] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (query.isError) {
    const error = query.error as ApiError;
    return (
      <Alert tone="error" title={error?.isNotFound ? "Statement not found" : "Could not load"}>
        {error?.isNotFound
          ? "This statement does not exist, or it belongs to another organization."
          : (error?.message ?? "Unexpected error.")}
      </Alert>
    );
  }

  const statement = query.data!;
  const openFlags = statement.flags.filter((flag) => flag.status === "open");

  return (
    <>
      <PageHeader
        title={statement.company_name ?? "Unknown company"}
        description={`${statement.filing_type} · fiscal ${statement.fiscal_year} ${statement.fiscal_period} · period ended ${formatDate(statement.period_end_date)}`}
        actions={
          <>
            {canRun && (
              <Button
                variant="secondary"
                loading={explain.isPending}
                onClick={() => explain.mutate()}
                disabled={statement.flags.length === 0}
              >
                Explain findings
              </Button>
            )}
            {canRun && (
              <Button loading={generateReport.isPending} onClick={() => generateReport.mutate()}>
                Generate report
              </Button>
            )}
          </>
        }
      />

      {explain.isError && (
        <Alert tone="warning" title="Explanations unavailable">
          {(explain.error as ApiError)?.message ??
            "The model could not be reached. Findings and scores are unaffected."}
        </Alert>
      )}

      {generateReport.isSuccess && (
        <div className="mb-4">
          <Alert tone="success" title="Report generated">
            <ButtonLink to={`/app/reports/${generateReport.data.id}`} size="sm" className="mt-2">
              Open report
            </ButtonLink>
          </Alert>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-5">
          <p className="text-sm font-medium text-ink-500">Risk score</p>
          <div className="mt-2">
            <RiskBadge score={statement.risk_score} />
          </div>
          <p className="mt-2 text-xs text-ink-400">
            A triage ordering derived from the findings below. Not a probability of fraud.
          </p>
        </Card>
        <Card className="p-5">
          <p className="text-sm font-medium text-ink-500">Open findings</p>
          <p className="mt-2 text-3xl font-bold text-ink-900">{openFlags.length}</p>
          <p className="mt-1 text-xs text-ink-400">{statement.flags.length} total</p>
        </Card>
        <Card className="p-5">
          <p className="text-sm font-medium text-ink-500">Line items</p>
          <p className="mt-2 text-3xl font-bold text-ink-900">{statement.line_items.length}</p>
          <p className="mt-1 text-xs text-ink-400">Source: {statement.source_dataset}</p>
        </Card>
      </div>

      <section className="mt-8">
        <h2 className="mb-3 text-lg font-semibold text-ink-900">
          Findings ({statement.flags.length})
        </h2>

        {statement.flags.length === 0 ? (
          <EmptyState
            title="No findings"
            description="No deterministic check raised a flag against this statement. That is not a clean opinion; it means these particular screens found nothing."
          />
        ) : (
          <div className="space-y-3">
            {statement.flags.map((flag) => (
              <Card key={flag.id} className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={flag.severity} />
                      <StatusBadge status={flag.status} />
                      <span className="text-xs text-ink-400">
                        {humanise(flag.detection_method)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm font-medium text-ink-900">{flag.description}</p>

                    {flag.explanation ? (
                      <p className="mt-2 rounded-lg bg-brand-50 p-3 text-sm leading-relaxed text-ink-700">
                        {flag.explanation}
                      </p>
                    ) : (
                      <p className="mt-2 text-xs text-ink-400">
                        No explanation generated yet.
                      </p>
                    )}

                    <details className="mt-3">
                      <summary className="cursor-pointer text-xs font-medium text-brand-600 hover:underline">
                        Evidence
                      </summary>
                      <pre className="mt-2 overflow-x-auto rounded-lg bg-ink-900 p-3 text-xs text-ink-100">
                        {JSON.stringify(flag.detail, null, 2)}
                      </pre>
                    </details>
                  </div>

                  {canTriage && flag.status === "open" && (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          triage.mutate({ flagId: flag.id, status: "acknowledged" })
                        }
                      >
                        Acknowledge
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => triage.mutate({ flagId: flag.id, status: "dismissed" })}
                      >
                        Dismiss
                      </Button>
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="border-b border-ink-200 px-5 py-4 text-sm font-semibold text-ink-900">
            Computed ratios
          </h2>
          <dl className="divide-y divide-ink-200">
            {RATIO_LABELS.map(({ key, label, percent }) => {
              const value = statement.ratios[key];
              return (
                <div key={key} className="flex items-center justify-between px-5 py-2.5">
                  <dt className="text-sm text-ink-600">{label}</dt>
                  <dd
                    className={
                      value === null
                        ? "text-sm text-ink-400"
                        : "text-sm font-medium tabular-nums text-ink-900"
                    }
                  >
                    {percent ? formatPercent(value) : formatRatio(value)}
                  </dd>
                </div>
              );
            })}
          </dl>
          <p className="border-t border-ink-200 px-5 py-3 text-xs text-ink-400">
            A ratio shown as not computable is missing an input. It is not zero.
          </p>
        </Card>

        <Card>
          <h2 className="border-b border-ink-200 px-5 py-4 text-sm font-semibold text-ink-900">
            Reported line items
          </h2>
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Reported line item values</caption>
              <tbody className="divide-y divide-ink-200">
                {statement.line_items.map((item) => (
                  <tr key={item.id}>
                    <th scope="row" className="px-5 py-2.5 text-left font-normal text-ink-600">
                      {item.tag}
                    </th>
                    <td className="px-5 py-2.5 text-right font-medium tabular-nums text-ink-900">
                      {formatMoney(item.value, item.unit)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}
