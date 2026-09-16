/**
 * Routing and application composition.
 *
 * The marketing site and the application share one bundle and one router, so
 * "Log in" is an in-app navigation rather than a page load, and the two halves
 * cannot drift apart visually.
 */

import { useEffect } from "react";
import { Navigate, Outlet, Route, Routes, useNavigate } from "react-router-dom";

import { setUnauthorizedHandler } from "@/api/client";
import { MarketingFooter, MarketingHeader } from "@/components/marketing/Chrome";
import { RequireAuth } from "@/components/app/Shell";
import { ButtonLink } from "@/components/ui";
import Dashboard from "@/pages/app/Dashboard";
import DocumentsPage from "@/pages/app/Documents";
import SearchPage from "@/pages/app/Search";
import SettingsPage from "@/pages/app/Settings";
import { ReportDetailPage, ReportsList } from "@/pages/app/Reports";
import { StatementDetail, StatementsList } from "@/pages/app/Statements";
import { LoginPage, RegisterPage } from "@/pages/marketing/Auth";
import Home from "@/pages/marketing/Home";
import { useAuth } from "@/store/auth";

function MarketingLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <MarketingHeader />
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <MarketingFooter />
    </div>
  );
}

function NotFound() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-32 text-center">
      <p className="text-6xl font-extrabold text-brand-600">404</p>
      <h1 className="text-2xl font-bold text-ink-900">Page not found</h1>
      <p className="text-ink-500">
        That page does not exist. It may have moved, or the link may be out of date.
      </p>
      <ButtonLink to="/">Back to home</ButtonLink>
    </div>
  );
}

/** Minimal legal pages, so the footer links are not dead ends. */
function LegalPage({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-3xl font-bold tracking-tight text-ink-900">{title}</h1>
      <div className="mt-6 space-y-4 text-sm leading-relaxed text-ink-600">{children}</div>
    </div>
  );
}

export default function App() {
  const navigate = useNavigate();
  const restore = useAuth((state) => state.restore);

  // Rebuild the session from the stored refresh token on first load. The
  // access token lives in memory only, so a reload always starts without one.
  useEffect(() => {
    void restore();
  }, [restore]);

  // When a refresh fails, the API client cannot navigate on its own. This hands
  // it a way to send the user to the login page exactly once, from anywhere.
  useEffect(() => {
    setUnauthorizedHandler(() => navigate("/login", { replace: true }));
  }, [navigate]);

  return (
    <Routes>
      <Route element={<MarketingLayout />}>
        <Route index element={<Home />} />
        <Route
          path="pricing"
          element={
            <LegalPage title="Pricing">
              <p>
                Ledgerline runs entirely on free-tier infrastructure and free-tier model APIs.
                The deployment documented in this repository has no per-seat cost.
              </p>
              <p>
                Commercial pricing has not been set. Replace this page before any public
                launch.
              </p>
            </LegalPage>
          }
        />
        <Route
          path="privacy"
          element={
            <LegalPage title="Privacy">
              <p>
                Uploaded documents and financial data are scoped to your organization and are
                never shared between tenants.
              </p>
              <p>
                Only computed evidence from a finding is sent to a language model, never your
                raw dataset. Prompts are hashed for usage metering; the prompt text itself is
                not stored.
              </p>
              <p>
                This is a summary for a demonstration deployment, not a legal privacy notice.
                Replace it with one reviewed by counsel before processing real client data.
              </p>
            </LegalPage>
          }
        />
        <Route
          path="terms"
          element={
            <LegalPage title="Terms">
              <p>
                Output from this platform is decision support. It is not an audit opinion, and
                a risk score is not a determination that any misstatement occurred.
              </p>
              <p>
                Placeholder text for a demonstration deployment. Replace with reviewed terms
                before any commercial use.
              </p>
            </LegalPage>
          }
        />
      </Route>

      <Route path="login" element={<LoginPage />} />
      <Route path="register" element={<RegisterPage />} />

      <Route path="app" element={<RequireAuth />}>
        <Route index element={<Navigate to="/app/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="statements" element={<StatementsList />} />
        <Route path="statements/:id" element={<StatementDetail />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="reports" element={<ReportsList />} />
        <Route path="reports/:id" element={<ReportDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>

      {/* Nested under the marketing layout so a 404 keeps the header and
          footer. MarketingLayout renders an Outlet, so this must be a child
          route rather than a element with children. */}
      <Route element={<MarketingLayout />}>
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
