/**
 * Display formatting.
 *
 * The money helpers take strings, not numbers. Line item values are exact
 * decimals that exceed IEEE 754's safe integer range; parsing one into a JS
 * number rounds it silently, which is precisely the corruption the backend's
 * Numeric column exists to prevent.
 */

/** Format an exact decimal string for display, without ever parsing it. */
export function formatMoney(value: string, currency = "USD"): string {
  const negative = value.startsWith("-");
  const digits = (negative ? value.slice(1) : value).split(".");
  const whole = digits[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const fraction = digits[1] && /[1-9]/.test(digits[1]) ? `.${digits[1].replace(/0+$/, "")}` : "";
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${negative ? "-" : ""}${symbol}${whole}${fraction}`;
}

/**
 * Abbreviate a large figure for a summary tile.
 *
 * Works on the digit count of the string rather than converting to a number,
 * because these values routinely exceed Number.MAX_SAFE_INTEGER and the
 * conversion would round before the abbreviation ever happened.
 */
export function abbreviateMoney(value: string): string {
  const negative = value.startsWith("-");
  const whole = (negative ? value.slice(1) : value).split(".")[0].replace(/^0+(?=\d)/, "");
  const sign = negative ? "-" : "";

  const units: Array<[number, string]> = [
    [13, "T"],
    [10, "B"],
    [7, "M"],
    [4, "K"],
  ];

  for (const [minDigits, suffix] of units) {
    if (whole.length >= minDigits) {
      // minDigits - 1 is the number of digits before the decimal point at this
      // scale: 13 digits is 1.0T, so one leading digit and a tenths digit.
      const lead = whole.length - (minDigits - 1);
      const head = whole.slice(0, lead);
      const tenth = whole[lead] ?? "0";
      return `${sign}$${head}.${tenth}${suffix}`;
    }
  }
  return formatMoney(value);
}

export function formatRatio(value: number | null, digits = 2): string {
  // An em-free explicit dash: a missing ratio is not zero and must not read as
  // one. See the backend note in detection/ratios.py.
  if (value === null || !Number.isFinite(value)) return "not computable";
  return value.toFixed(digits);
}

export function formatPercent(value: number | null, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return "not computable";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatDate(value: string | null): string {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatDateTime(value: string | null): string {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

/** Turn a snake_case identifier into readable words. */
export function humanise(value: string): string {
  return value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export type RiskBand = "none" | "low" | "elevated" | "high" | "unscored";

/** Bucket a risk score. Mirrors `_risk_band` in reporting/builder.py. */
export function riskBand(score: number | null): RiskBand {
  if (score === null) return "unscored";
  if (score >= 70) return "high";
  if (score >= 40) return "elevated";
  if (score > 0) return "low";
  return "none";
}

export const RISK_BAND_LABEL: Record<RiskBand, string> = {
  high: "High risk",
  elevated: "Elevated risk",
  low: "Low risk",
  none: "No findings",
  // Deliberately distinct from "No findings": "we have not looked" and "we
  // looked and found nothing" are very different things to tell an auditor.
  unscored: "Not yet assessed",
};
