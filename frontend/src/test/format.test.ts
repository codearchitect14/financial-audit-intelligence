/**
 * Formatting tests.
 *
 * The money helpers matter more than they look. Line item values are exact
 * decimals that exceed the safe integer range; anything that parses one into a
 * JS number silently corrupts it, which is exactly what the backend's Numeric
 * column exists to prevent.
 */

import { describe, expect, it } from "vitest";

import {
  RISK_BAND_LABEL,
  abbreviateMoney,
  formatBytes,
  formatMoney,
  formatPercent,
  formatRatio,
  humanise,
  riskBand,
} from "@/lib/format";

describe("formatMoney", () => {
  it("adds thousands separators", () => {
    expect(formatMoney("1000000")).toBe("$1,000,000");
  });

  it("handles values beyond Number.MAX_SAFE_INTEGER without losing digits", () => {
    // 2^53 is about 9.007e15. This is larger, and a parseFloat round trip
    // would change the final digits.
    const huge = "12345678901234567890";
    expect(formatMoney(huge)).toContain("12,345,678,901,234,567,890");
  });

  it("drops trailing zeros from the Numeric(28,4) padding", () => {
    expect(formatMoney("1000000.0000")).toBe("$1,000,000");
  });

  it("keeps meaningful decimals", () => {
    expect(formatMoney("1234.5600")).toBe("$1,234.56");
  });

  it("handles negatives", () => {
    expect(formatMoney("-4200")).toBe("-$4,200");
  });

  it("handles zero", () => {
    expect(formatMoney("0")).toBe("$0");
  });

  it("uses a currency prefix for non-USD units", () => {
    expect(formatMoney("100", "EUR")).toBe("EUR 100");
  });
});

describe("abbreviateMoney", () => {
  it.each([
    ["352755000000", "$352.7B"],
    ["1500000", "$1.5M"],
    ["2500", "$2.5K"],
    ["1234567890123", "$1.2T"],
    ["-4200000", "-$4.2M"],
  ])("abbreviates %s to %s", (input, expected) => {
    expect(abbreviateMoney(input)).toBe(expected);
  });

  it("leaves small values fully formatted", () => {
    expect(abbreviateMoney("999")).toBe("$999");
  });
});

describe("formatRatio", () => {
  it("formats a number to two places", () => {
    expect(formatRatio(1.23456)).toBe("1.23");
  });

  it("never renders a missing ratio as zero", () => {
    // Zero is a real, meaningful value for most of these. Showing "0.00" for a
    // ratio that could not be computed would invent a finding.
    expect(formatRatio(null)).toBe("not computable");
    expect(formatRatio(null)).not.toContain("0");
  });

  it("treats a non-finite value as not computable", () => {
    expect(formatRatio(Number.POSITIVE_INFINITY)).toBe("not computable");
    expect(formatRatio(Number.NaN)).toBe("not computable");
  });

  it("formats a genuine zero as zero", () => {
    expect(formatRatio(0)).toBe("0.00");
  });
});

describe("formatPercent", () => {
  it("scales and suffixes", () => {
    expect(formatPercent(0.1234)).toBe("12.3%");
  });

  it("reports a missing value as not computable", () => {
    expect(formatPercent(null)).toBe("not computable");
  });
});

describe("riskBand", () => {
  it.each([
    [null, "unscored"],
    [0, "none"],
    [15, "low"],
    [50, "elevated"],
    [85, "high"],
  ] as const)("bands %s as %s", (score, expected) => {
    expect(riskBand(score)).toBe(expected);
  });

  it("distinguishes unscored from no findings", () => {
    // "We have not looked" and "we looked and found nothing" are very different
    // things to put in front of an auditor.
    expect(RISK_BAND_LABEL.unscored).not.toBe(RISK_BAND_LABEL.none);
  });

  it("mirrors the backend thresholds exactly", () => {
    // Matching _risk_band in reporting/builder.py. A boundary that drifts would
    // make the UI and an exported report disagree about the same statement.
    expect(riskBand(69.9)).toBe("elevated");
    expect(riskBand(70)).toBe("high");
    expect(riskBand(39.9)).toBe("low");
    expect(riskBand(40)).toBe("elevated");
  });
});

describe("formatBytes", () => {
  it.each([
    [512, "512 B"],
    [2048, "2.0 KB"],
    [5 * 1024 * 1024, "5.0 MB"],
  ])("formats %s as %s", (input, expected) => {
    expect(formatBytes(input)).toBe(expected);
  });
});

describe("humanise", () => {
  it("turns a snake_case identifier into words", () => {
    expect(humanise("accruals_ratio")).toBe("Accruals ratio");
  });
});
