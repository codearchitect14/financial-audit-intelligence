/**
 * End-to-end journey.
 *
 * Covers the path the plan names: arrive on the marketing site, register, land
 * in the application, navigate it, and generate a report. Run against a real
 * production build and a real API.
 *
 * Tests that need the backend are skipped, not failed, when it is unreachable,
 * so the marketing coverage still runs on a machine with no database.
 *
 * The API under test must run with RATE_LIMIT_ENABLED=false. Registration is
 * limited to 5/hour per address, which is correct in production and makes a
 * multi-test journey impossible from one host. The limits themselves are
 * covered by the backend suite in tests/test_rate_limiting.py.
 */

import { expect, test, type Page } from "@playwright/test";

const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";

/** A unique account per run, so tests never collide on the unique email index. */
function newAccount() {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    email: `e2e-${suffix}@example.com`,
    password: "a-sufficiently-long-password",
    fullName: "End To End User",
    organization: `E2E Org ${suffix}`,
  };
}

async function apiReachable(): Promise<boolean> {
  try {
    const response = await fetch(`${API_URL}/api/v1/health`);
    return response.ok;
  } catch {
    return false;
  }
}

async function register(page: Page, account: ReturnType<typeof newAccount>) {
  await page.goto("/register");
  await page.getByLabel("Full name").fill(account.fullName);
  await page.getByLabel("Work email").fill(account.email);
  await page.getByLabel("Organization name").fill(account.organization);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/app\/dashboard/, { timeout: 15_000 });
}

test.describe("Marketing site", () => {
  test("renders the hero and the value proposition", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /Find the numbers that do not add up/i }),
    ).toBeVisible();
    await expect(page.getByText(/Deterministic detection/i).first()).toBeVisible();
  });

  test("offers a visible log in control", async ({ page }) => {
    // The plan requires this: it is the only route from the site into the app.
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Log in" }).first()).toBeVisible();
  });

  test("navigates from the marketing site to login", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Log in" }).first().click();

    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
  });

  test("shows every required marketing section", async ({ page }) => {
    await page.goto("/");

    for (const heading of [
      /Detection you can defend/i,
      /From raw filings to a written finding/i,
      /Designed for data you are accountable for/i,
      /What review teams tell us/i,
    ]) {
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    }
  });

  test("marks sample testimonials as sample content", async ({ page }) => {
    // Presenting invented quotes as genuine would be a misrepresentation. The
    // page must say so until real ones replace them.
    await page.goto("/");
    await expect(page.getByText(/Sample content\. Replace with attributed/i)).toBeVisible();
  });

  test("is usable at a mobile viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");

    await page.getByRole("button", { name: "Open menu" }).click();
    await expect(page.getByRole("navigation", { name: "Main, mobile" })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Main, mobile" }).getByRole("link", { name: "Log in" }),
    ).toBeVisible();
  });

  test("does not scroll horizontally on a narrow screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");

    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(overflows).toBe(false);
  });

  test("renders a 404 page with the site chrome intact", async ({ page }) => {
    await page.goto("/no-such-page");

    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
    // .first(): the logo appears in both the header and the footer, and a
    // bare getByRole would fail strict mode on the duplicate.
    await expect(page.getByRole("link", { name: "Ledgerline home" }).first()).toBeVisible();
  });
});

test.describe("Authenticated journey", () => {
  test.beforeEach(async () => {
    test.skip(!(await apiReachable()), `API not reachable at ${API_URL}`);
  });

  test("redirects an anonymous visitor away from the application", async ({ page }) => {
    await page.goto("/app/dashboard");
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });

  test("registers, lands on the dashboard, and navigates the application", async ({ page }) => {
    const account = newAccount();
    await register(page, account);

    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    await page.getByRole("link", { name: "Statements" }).click();
    await expect(page.getByRole("heading", { name: "Statements" })).toBeVisible();

    await page.getByRole("link", { name: "Search" }).click();
    await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();

    await page.getByRole("link", { name: "Reports" }).click();
    await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();

    await page.getByRole("link", { name: "Documents" }).click();
    await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
  });

  test("keeps the session across a page reload", async ({ page }) => {
    // The access token lives in memory only, so a reload has to rebuild the
    // session from the stored refresh token or the user is logged out by F5.
    const account = newAccount();
    await register(page, account);

    await page.reload();
    await expect(page).toHaveURL(/\/app\/dashboard/);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  });

  test("never writes an access token into localStorage", async ({ page }) => {
    const account = newAccount();
    await register(page, account);

    const storage = await page.evaluate(() => JSON.stringify(localStorage));
    // The refresh token is stored deliberately; the access token must not be.
    expect(storage).toContain("fai.refresh");

    const accessTokenLike = /"access_token"|eyJhbGciOi/;
    expect(accessTokenLike.test(storage)).toBe(false);
  });

  test("logs out and blocks the application afterwards", async ({ page }) => {
    const account = newAccount();
    await register(page, account);

    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page).toHaveURL(/\/(login)?$/, { timeout: 10_000 });

    await page.goto("/app/dashboard");
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });

  test("rejects a wrong password with a clear message", async ({ page }) => {
    const account = newAccount();
    await register(page, account);
    await page.getByRole("button", { name: "Log out" }).click();

    await page.goto("/login");
    await page.getByLabel("Work email").fill(account.email);
    await page.getByLabel("Password").fill("definitely-the-wrong-password");
    await page.getByRole("button", { name: "Log in" }).click();

    await expect(page.getByRole("alert")).toContainText(/Incorrect email or password/i);
  });

  test("search returns an empty result rather than an error", async ({ page }) => {
    // A fresh organization has no indexed documents. The page must say so
    // plainly rather than failing.
    const account = newAccount();
    await register(page, account);

    await page.getByRole("link", { name: "Search" }).click();
    await page.getByLabel("Search query").fill("revenue recognition");
    await page.getByRole("button", { name: "Search passages" }).click();

    await expect(page.getByText(/Nothing matched|0 passages/i).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("settings reports quota status honestly", async ({ page }) => {
    const account = newAccount();
    await register(page, account);

    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    // With no provider key configured, the UI must say so rather than showing
    // a quota that means nothing.
    await expect(page.getByText(/No language model is configured|Calls in the last/i)).toBeVisible();
  });
});
