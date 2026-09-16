import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration.
 *
 * The suite runs against a real build served by `vite preview`, not the dev
 * server: a production bundle is what users get, and a dev-only failure mode
 * (an unminified path, a missing chunk) would go unnoticed otherwise.
 *
 * The backend is NOT started here. It needs Postgres, migrations, and an
 * environment, so CI starts it as a service and passes E2E_API_URL. Locally,
 * start it yourself first.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // A test that only passes on a retry is flaky, and CI should say so rather
  // than hide it. Retries exist for genuine infrastructure blips only.
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:4173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: {
    // vite preview directly, not "npm run build && npm run preview": the
    // chained form is shell-dependent and the npm arg forwarding differs
    // across platforms. CI builds in its own step; locally, run
    // "npm run build" first.
    // --host 127.0.0.1 is not optional. Vite binds "localhost" by default,
    // which on Windows resolves to ::1 only, so a 127.0.0.1 health check
    // never connects and Playwright waits out its full timeout.
    command: "npx vite preview --port 4173 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      VITE_PROXY_TARGET: process.env.E2E_API_URL ?? "http://127.0.0.1:8000",
    },
  },
});
