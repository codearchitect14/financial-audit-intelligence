/**
 * Shared UI primitives.
 *
 * Small, unopinionated, and deliberately in one file: the set is short enough
 * that splitting it would cost more in imports than it saves in navigation.
 * Every interactive element carries a focus style and an accessible name.
 */

import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/cn";
import { RISK_BAND_LABEL, riskBand } from "@/lib/format";
import type { FlagSeverity } from "@/api/types";

/* -------------------------------------------------------------------------- */
/* Button                                                                      */
/* -------------------------------------------------------------------------- */
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-300",
  secondary:
    "bg-white text-ink-800 ring-1 ring-inset ring-ink-300 hover:bg-ink-50 disabled:text-ink-400",
  ghost: "text-ink-700 hover:bg-ink-100 disabled:text-ink-400",
  danger: "bg-severity-high text-white hover:brightness-110 disabled:opacity-50",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-sm",
  lg: "px-6 py-3 text-base",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className,
  children,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      // aria-busy rather than swapping the label: a screen reader announces the
      // state change without the accessible name shifting under the user.
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition",
        "disabled:cursor-not-allowed",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

export function ButtonLink({
  to,
  variant = "primary",
  size = "md",
  className,
  children,
  onClick,
}: {
  to: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: ReactNode;
  onClick?: () => void;
}) {
  return (
    <Link
      to={to}
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
    >
      {children}
    </Link>
  );
}

/* -------------------------------------------------------------------------- */
/* Feedback                                                                    */
/* -------------------------------------------------------------------------- */
export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("animate-spin", className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

export function Alert({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warning" | "error" | "success";
  title?: string;
  children: ReactNode;
}) {
  const tones = {
    info: "bg-brand-50 text-brand-900 ring-brand-200",
    warning: "bg-amber-50 text-amber-900 ring-amber-200",
    error: "bg-red-50 text-red-900 ring-red-200",
    success: "bg-emerald-50 text-emerald-900 ring-emerald-200",
  };
  return (
    <div
      // assertive only for errors: a polite live region would let a failure
      // message sit unannounced until the user next moves focus.
      role={tone === "error" ? "alert" : "status"}
      className={cn("rounded-lg px-4 py-3 text-sm ring-1 ring-inset", tones[tone])}
    >
      {title && <p className="font-semibold">{title}</p>}
      <div className={title ? "mt-1" : undefined}>{children}</div>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed border-ink-300 px-6 py-12 text-center">
      <p className="text-base font-semibold text-ink-800">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-ink-500">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-ink-200", className)} aria-hidden="true" />;
}

/* -------------------------------------------------------------------------- */
/* Layout                                                                      */
/* -------------------------------------------------------------------------- */
export function Card({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...props} className={cn("rounded-xl bg-white ring-1 ring-ink-200 shadow-sm", className)}>
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4 pb-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-900">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-ink-500">{description}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </header>
  );
}

/* -------------------------------------------------------------------------- */
/* Domain badges                                                               */
/* -------------------------------------------------------------------------- */
const SEVERITY_STYLES: Record<FlagSeverity, string> = {
  critical: "bg-red-100 text-severity-critical ring-red-200",
  high: "bg-red-50 text-severity-high ring-red-200",
  medium: "bg-amber-50 text-severity-medium ring-amber-200",
  low: "bg-ink-100 text-severity-low ring-ink-200",
  info: "bg-ink-50 text-severity-info ring-ink-200",
};

export function SeverityBadge({ severity }: { severity: FlagSeverity }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ring-1 ring-inset",
        SEVERITY_STYLES[severity],
      )}
    >
      {severity}
    </span>
  );
}

const BAND_STYLES = {
  high: "bg-red-50 text-severity-high ring-red-200",
  elevated: "bg-amber-50 text-severity-medium ring-amber-200",
  low: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  none: "bg-ink-100 text-ink-600 ring-ink-200",
  unscored: "bg-ink-50 text-ink-500 ring-ink-200",
} as const;

export function RiskBadge({ score }: { score: number | null }) {
  const band = riskBand(score);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ring-inset",
        BAND_STYLES[band],
      )}
      // The number alone is meaningless without the band, and the band alone
      // loses the ordering, so both are always shown together.
      title={RISK_BAND_LABEL[band]}
    >
      {score === null ? "Not assessed" : score.toFixed(0)}
      <span className="font-normal opacity-75">{RISK_BAND_LABEL[band]}</span>
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    open: "bg-brand-50 text-brand-800 ring-brand-200",
    acknowledged: "bg-amber-50 text-amber-800 ring-amber-200",
    resolved: "bg-emerald-50 text-emerald-800 ring-emerald-200",
    dismissed: "bg-ink-100 text-ink-600 ring-ink-200",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium capitalize ring-1 ring-inset",
        styles[status] ?? styles.dismissed,
      )}
    >
      {status}
    </span>
  );
}
