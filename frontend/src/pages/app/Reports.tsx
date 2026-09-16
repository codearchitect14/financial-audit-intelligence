/**
 * Report list and detail.
 */

import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { reports } from "@/api/endpoints";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  PageHeader,
  RiskBadge,
  SeverityBadge,
  Skeleton,
} from "@/components/ui";
import { formatDateTime, formatPercent, formatRatio, humanise } from "@/lib/format";
import type { FlagSeverity } from "@/api/types";

export function ReportsList() {
  const list = useQuery({
    queryKey: ["reports"],
    queryFn: () => reports.list({ limit: 50 }),
  });

  return (
    <>
      <PageHeader
        title="Reports"
        description="Generated from computed figures and persisted findings. Every number comes from stored data; only the narrative is written by a model."
      />

      <Card className="overflow-hidden">
        {list.isLoading ? (
          <div className="space-y-2 p-5">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-12" />
            ))}
          </div>
        ) : (list.data?.total ?? 0) === 0 ? (
          <div className="p-6">
            <EmptyState
              title="No reports yet"
              description="Open a statement and choose Generate report to produce one."
              action={
                <Link to="/app/statements" className="text-sm font-medium text-brand-600 hover:underline">
                  Browse statements
                </Link>
              }
            />
          </div>
        ) : (
          <ul className="divide-y divide-ink-200">
            {list.data?.items.map((report) => (
              <li key={report.id}>
                <Link
                  to={`/app/reports/${report.id}`}
                  className="flex items-center justify-between gap-4 px-5 py-4 transition hover:bg-ink-50"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-ink-900">
                      {report.title}
                    </span>
                    <span className="block text-xs text-ink-500">
                      Generated {formatDateTime(report.generated_at ?? report.created_at)}
                    </span>
                  </span>
                  <RiskBadge score={report.risk_score} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

/** Shape of the stored report JSON. Narrow, because only some of it renders. */
interface ReportFacts {
  company?: { name?: string; cik?: string | null; sector?: string | null };
  period?: { fiscal_year?: number; fiscal_period?: string; filing_type?: string };
  risk?: { score?: number | null; band?: string; basis?: string };
  ratios?: Record<string, number | null>;
  findings?: Array<{
    flag_type: string;
    severity: FlagSeverity;
    status: string;
    description: string;
    explanation: string | null;
  }>;
  counts?: { total_findings?: number; open_findings?: number };
}

interface NarrativeSection {
  section: string;
  heading: string;
  body: string;
  cached?: boolean;
}

const PERCENT_RATIOS = new Set([
  "gross_margin",
  "net_margin",
  "operating_margin",
  "return_on_assets",
  "accruals_ratio",
]);

export function ReportDetailPage() {
  const { id = "" } = useParams();

  const query = useQuery({
    queryKey: ["report", id],
    queryFn: () => reports.get(id),
    enabled: Boolean(id),
  });

  const formats = useQuery({
    queryKey: ["report-formats"],
    queryFn: reports.formats,
    staleTime: 5 * 60_000,
  });

  async function download(fmt: "html" | "pdf") {
    // Fetched as a blob rather than opened as a link: a plain anchor cannot
    // carry the Authorization header and would come back 401.
    const blob = await reports.exportBlob(id, fmt);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `report-${id}.${fmt}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (query.isError) {
    const error = query.error as ApiError;
    return (
      <Alert tone="error" title={error?.isNotFound ? "Report not found" : "Could not load"}>
        {error?.isNotFound
          ? "This report does not exist, or it belongs to another organization."
          : (error?.message ?? "Unexpected error.")}
      </Alert>
    );
  }

  const report = query.data!;
  const content = report.content as {
    facts?: ReportFacts;
    narrative?: NarrativeSection[];
  };
  const facts = content.facts ?? {};
  const narrative = content.narrative ?? [];
  const ratios = Object.entries(facts.ratios ?? {}).filter(([, value]) => value !== null);

  return (
    <>
      <PageHeader
        title={report.title}
        description={`Generated ${formatDateTime(report.generated_at ?? report.created_at)}`}
        actions={
          <>
            <Button variant="secondary" onClick={() => void download("html")}>
              Export HTML
            </Button>
            {formats.data?.pdf ? (
              <Button onClick={() => void download("pdf")}>Export PDF</Button>
            ) : (
              <Button
                disabled
                title={formats.data?.pdf_unavailable_reason ?? "PDF export is unavailable"}
              >
                PDF unavailable
              </Button>
            )}
          </>
        }
      />

      {report.error && (
        <div className="mb-4">
          <Alert tone="warning" title="Narrative incomplete">
            {report.error} All figures and findings below are complete and unaffected.
          </Alert>
        </div>
      )}

      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-4">
          <RiskBadge score={report.risk_score} />
          <span className="text-sm text-ink-500">
            {facts.counts?.total_findings ?? 0} finding
            {facts.counts?.total_findings === 1 ? "" : "s"},{" "}
            {facts.counts?.open_findings ?? 0} open
          </span>
        </div>
        {facts.risk?.basis && (
          <p className="mt-3 rounded-lg bg-ink-50 px-4 py-3 text-xs text-ink-600">
            {facts.risk.basis}
          </p>
        )}
      </Card>

      {narrative.length > 0 ? (
        <section className="mt-6 space-y-4">
          {narrative.map((section) => (
            <Card key={section.section} className="p-5">
              <h2 className="text-base font-semibold text-ink-900">{section.heading}</h2>
              <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-ink-700">
                {section.body}
              </p>
            </Card>
          ))}
        </section>
      ) : (
        <div className="mt-6">
          <Alert tone="info" title="No narrative sections">
            This report was generated without model narrative. Every figure and finding is
            present and correct.
          </Alert>
        </div>
      )}

      <section className="mt-8">
        <h2 className="mb-3 text-lg font-semibold text-ink-900">Findings</h2>
        {(facts.findings?.length ?? 0) === 0 ? (
          <EmptyState
            title="No findings"
            description="No deterministic check raised a flag against this statement."
          />
        ) : (
          <div className="space-y-3">
            {facts.findings?.map((finding) => (
              <Card key={finding.flag_type} className="p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={finding.severity} />
                  <span className="text-xs capitalize text-ink-400">{finding.status}</span>
                </div>
                <p className="mt-2 text-sm font-medium text-ink-900">{finding.description}</p>
                {finding.explanation && (
                  <p className="mt-2 text-sm leading-relaxed text-ink-600">
                    {finding.explanation}
                  </p>
                )}
              </Card>
            ))}
          </div>
        )}
      </section>

      {ratios.length > 0 && (
        <Card className="mt-8">
          <h2 className="border-b border-ink-200 px-5 py-4 text-sm font-semibold text-ink-900">
            Computed ratios
          </h2>
          <dl className="divide-y divide-ink-200">
            {ratios.map(([name, value]) => (
              <div key={name} className="flex items-center justify-between px-5 py-2.5">
                <dt className="text-sm text-ink-600">{humanise(name)}</dt>
                <dd className="text-sm font-medium tabular-nums text-ink-900">
                  {PERCENT_RATIOS.has(name) ? formatPercent(value) : formatRatio(value)}
                </dd>
              </div>
            ))}
          </dl>
        </Card>
      )}
    </>
  );
}
