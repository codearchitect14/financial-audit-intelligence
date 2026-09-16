/**
 * Dashboard: summary tiles, a risk trend chart, and the highest-risk queue.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { dashboard, insights, statements } from "@/api/endpoints";
import { Alert, Card, EmptyState, PageHeader, RiskBadge, Skeleton } from "@/components/ui";
import { formatDate } from "@/lib/format";

function Tile({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "warning" | "danger";
}) {
  const tones = {
    default: "text-ink-900",
    warning: "text-severity-medium",
    danger: "text-severity-high",
  };
  return (
    <Card className="p-5">
      <p className="text-sm font-medium text-ink-500">{label}</p>
      <p className={`mt-2 text-3xl font-bold tracking-tight ${tones[tone]}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-400">{hint}</p>}
    </Card>
  );
}

export default function Dashboard() {
  const summary = useQuery({
    queryKey: ["dashboard"],
    queryFn: dashboard.summary,
  });

  const riskiest = useQuery({
    queryKey: ["statements", "riskiest"],
    queryFn: () => statements.list({ limit: 8, min_risk_score: 1 }),
  });

  const budget = useQuery({
    queryKey: ["llm-budget"],
    queryFn: insights.budget,
    // A quota display that is a minute stale is fine, and polling it would
    // itself be the most frequent request the dashboard makes.
    staleTime: 60_000,
  });

  // Risk distribution across the returned statements, bucketed. Charting a
  // real time series would need a per-period aggregate endpoint; this shows
  // the shape of the current queue, which is what the tiles summarise.
  const distribution = (() => {
    const buckets = [0, 20, 40, 60, 80].map((floor) => ({
      band: `${floor}-${floor + 19}`,
      count: 0,
    }));
    for (const statement of riskiest.data?.items ?? []) {
      const score = statement.risk_score ?? 0;
      const index = Math.min(Math.floor(score / 20), buckets.length - 1);
      buckets[index].count += 1;
    }
    return buckets;
  })();

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Everything below is produced by deterministic checks. Risk scores order your queue; they are not a probability of fraud."
      />

      {summary.isError && (
        <Alert tone="error" title="Could not load the summary">
          The API did not respond. Findings already generated are unaffected.
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {summary.isLoading ? (
          Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28" />)
        ) : (
          <>
            <Tile
              label="Statements analysed"
              value={String(summary.data?.total_statements ?? 0)}
              hint="Across the public corpus and your uploads"
            />
            <Tile
              label="Open findings"
              value={String(summary.data?.open_flags ?? 0)}
              tone="warning"
              hint="Awaiting triage"
            />
            <Tile
              label="High severity"
              value={String(summary.data?.critical_flags ?? 0)}
              tone="danger"
              hint="High or critical, still open"
            />
            <Tile
              label="Average risk"
              value={
                summary.data?.average_risk_score === null ||
                summary.data?.average_risk_score === undefined
                  ? "Not scored"
                  : summary.data.average_risk_score.toFixed(1)
              }
              hint="Across scored statements only"
            />
          </>
        )}
      </div>

      {budget.data && !budget.data.providers_configured && (
        <div className="mt-6">
          <Alert tone="info" title="No language model configured">
            Detection, scoring, search, and reports all work. Only generated narrative is
            unavailable until an API key is set.
          </Alert>
        </div>
      )}

      {budget.data?.exhausted && (
        <div className="mt-6">
          <Alert tone="warning" title="Daily model quota reached">
            New explanations will use the fallback provider. Cached explanations are unaffected.
          </Alert>
        </div>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-5">
        <Card className="p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold text-ink-900">Risk distribution</h2>
          <p className="mt-0.5 text-xs text-ink-500">Scored statements by band</p>
          <div className="mt-4 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={distribution} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
                <defs>
                  <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#1f43e0" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#1f43e0" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e0e5ec" vertical={false} />
                <XAxis dataKey="band" tick={{ fontSize: 11, fill: "#6b7787" }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "#6b7787" }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e0e5ec" }}
                />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#1f43e0"
                  strokeWidth={2}
                  fill="url(#riskFill)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="lg:col-span-3">
          <div className="flex items-center justify-between border-b border-ink-200 px-5 py-4">
            <h2 className="text-sm font-semibold text-ink-900">Highest risk statements</h2>
            <Link to="/app/statements" className="text-xs font-medium text-brand-600 hover:underline">
              View all
            </Link>
          </div>

          {riskiest.isLoading ? (
            <div className="space-y-2 p-5">
              {Array.from({ length: 5 }, (_, index) => (
                <Skeleton key={index} className="h-10" />
              ))}
            </div>
          ) : (riskiest.data?.items.length ?? 0) === 0 ? (
            <div className="p-5">
              <EmptyState
                title="Nothing scored yet"
                description="Ingest filings and run the analysis job to populate this queue."
              />
            </div>
          ) : (
            <ul className="divide-y divide-ink-200">
              {riskiest.data?.items.map((statement) => (
                <li key={statement.id}>
                  <Link
                    to={`/app/statements/${statement.id}`}
                    className="flex items-center justify-between gap-4 px-5 py-3 transition hover:bg-ink-50"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-ink-900">
                        {statement.company_name ?? "Unknown company"}
                      </span>
                      <span className="block text-xs text-ink-500">
                        {statement.filing_type} · FY{statement.fiscal_year}{" "}
                        {statement.fiscal_period} · {formatDate(statement.period_end_date)}
                      </span>
                    </span>
                    <RiskBadge score={statement.risk_score} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
