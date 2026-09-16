/**
 * Component tests.
 *
 * Focused on the places where a rendering mistake would mislead a user about
 * risk, or would let the interface imply a permission the server does not
 * grant.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import {
  Alert,
  Button,
  EmptyState,
  RiskBadge,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import { hasRole } from "@/store/auth";
import type { User } from "@/api/types";

function wrap(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RiskBadge", () => {
  it("shows the score alongside its band", () => {
    // The number alone means nothing to a reader; the band alone loses the
    // ordering. Both are always shown together.
    wrap(<RiskBadge score={82} />);

    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText("High risk")).toBeInTheDocument();
  });

  it("never renders an unscored statement as zero risk", () => {
    wrap(<RiskBadge score={null} />);

    expect(screen.getByText("Not assessed")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("distinguishes a genuine zero from unscored", () => {
    wrap(<RiskBadge score={0} />);
    expect(screen.getByText("No findings")).toBeInTheDocument();
  });
});

describe("SeverityBadge", () => {
  it.each(["critical", "high", "medium", "low", "info"] as const)(
    "renders %s",
    (severity) => {
      wrap(<SeverityBadge severity={severity} />);
      expect(screen.getByText(severity)).toBeInTheDocument();
    },
  );
});

describe("StatusBadge", () => {
  it("renders a known status", () => {
    wrap(<StatusBadge status="open" />);
    expect(screen.getByText("open")).toBeInTheDocument();
  });

  it("falls back gracefully for an unknown status", () => {
    // A new status added server-side must not crash the list that renders it.
    wrap(<StatusBadge status="something_new" />);
    expect(screen.getByText("something_new")).toBeInTheDocument();
  });
});

describe("Button", () => {
  it("calls its handler", async () => {
    const onClick = vi.fn();
    wrap(<Button onClick={onClick}>Run analysis</Button>);

    await userEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("is disabled and marked busy while loading", async () => {
    const onClick = vi.fn();
    wrap(
      <Button loading onClick={onClick}>
        Generate report
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Generate report" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");

    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps its accessible name while loading", () => {
    // Swapping the label for a spinner would move the accessible name under a
    // screen reader user mid-interaction.
    wrap(<Button loading>Generate report</Button>);
    expect(screen.getByRole("button", { name: "Generate report" })).toBeInTheDocument();
  });
});

describe("Alert", () => {
  it("announces an error assertively", () => {
    // A polite region would let a failure sit unannounced until the user next
    // moved focus.
    wrap(<Alert tone="error">Upload rejected</Alert>);
    expect(screen.getByRole("alert")).toHaveTextContent("Upload rejected");
  });

  it("uses a status region for non-errors", () => {
    wrap(<Alert tone="info">Quota reached</Alert>);
    expect(screen.getByRole("status")).toHaveTextContent("Quota reached");
  });
});

describe("EmptyState", () => {
  it("renders guidance rather than a blank panel", () => {
    wrap(
      <EmptyState title="No statements" description="Ingest a quarter of filings first." />,
    );

    expect(screen.getByText("No statements")).toBeInTheDocument();
    expect(screen.getByText("Ingest a quarter of filings first.")).toBeInTheDocument();
  });
});

describe("hasRole", () => {
  const user = (role: User["role"]): User => ({
    id: "1",
    email: "a@b.c",
    full_name: "Test",
    role,
    organization_id: "o",
    is_active: true,
    created_at: "",
    last_login_at: null,
  });

  it("mirrors the backend hierarchy", () => {
    expect(hasRole(user("admin"), "viewer")).toBe(true);
    expect(hasRole(user("auditor"), "reviewer")).toBe(true);
    expect(hasRole(user("viewer"), "auditor")).toBe(false);
    expect(hasRole(user("reviewer"), "admin")).toBe(false);
  });

  it("denies when there is no user", () => {
    expect(hasRole(null, "viewer")).toBe(false);
  });

  it("fails closed on an unrecognised role", () => {
    // A role added server-side that this build does not know about must not be
    // treated as privileged.
    expect(hasRole({ ...user("viewer"), role: "superuser" as never }, "viewer")).toBe(false);
  });
});
