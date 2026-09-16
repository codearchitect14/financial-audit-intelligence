/**
 * Authenticated application shell: sidebar, top bar, and the route guard.
 */

import { useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";

import { Button, Spinner } from "@/components/ui";
import { Logo } from "@/components/marketing/Chrome";
import { cn } from "@/lib/cn";
import { hasRole, useAuth } from "@/store/auth";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  /** Minimum role. Hides the link only; the server enforces the rule. */
  minimumRole?: string;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/app/dashboard", label: "Dashboard", icon: "M4 5h6v6H4zM14 5h6v4h-6zM14 13h6v6h-6zM4 15h6v4H4z" },
  { to: "/app/statements", label: "Statements", icon: "M8 6h11M8 12h11M8 18h11M4 6h.01M4 12h.01M4 18h.01" },
  { to: "/app/search", label: "Search", icon: "M21 21l-4.35-4.35M17 10a7 7 0 11-14 0 7 7 0 0114 0z" },
  { to: "/app/documents", label: "Documents", icon: "M13 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V9z M13 3v6h6" },
  { to: "/app/reports", label: "Reports", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.6L19 9.4V19a2 2 0 01-2 2z" },
  { to: "/app/settings", label: "Settings", icon: "M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-2.9 1.17V21a2 2 0 11-4 0v-.09A1.65 1.65 0 007 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 002.6 15H2a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 4.6V4a2 2 0 114 0v.09a1.65 1.65 0 001.17 2.9l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0019.4 15z", minimumRole: "admin" },
];

/**
 * Route guard.
 *
 * Waits for the initial session restore before deciding. Without that wait a
 * page reload flashes the login screen and then bounces back, and any
 * in-progress navigation is lost.
 */
export function RequireAuth() {
  const { user, initialising } = useAuth();
  const location = useLocation();

  if (initialising) {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status">
        <Spinner className="h-8 w-8 text-brand-600" />
        <span className="sr-only">Restoring your session</span>
      </div>
    );
  }

  if (!user) {
    // Remember where they were headed so login can return them there.
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }

  return <AppShell />;
}

function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { user, logout } = useAuth();

  const visibleItems = NAV_ITEMS.filter(
    (item) => !item.minimumRole || hasRole(user, item.minimumRole),
  );

  return (
    <div className="flex min-h-screen bg-ink-50">
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      {/* Mobile scrim */}
      {sidebarOpen && (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-ink-900/40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-label="Close navigation"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-64 border-r border-ink-200 bg-white transition-transform lg:static lg:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 items-center border-b border-ink-200 px-4">
          <Logo />
        </div>

        <nav className="space-y-1 p-3" aria-label="Application">
          {visibleItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive
                    ? "bg-brand-50 text-brand-700"
                    : "text-ink-600 hover:bg-ink-100 hover:text-ink-900",
                )
              }
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d={item.icon} />
              </svg>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="absolute inset-x-0 bottom-0 border-t border-ink-200 p-3">
          <div className="rounded-lg bg-ink-50 px-3 py-2">
            <p className="truncate text-sm font-medium text-ink-900">{user?.full_name}</p>
            <p className="truncate text-xs capitalize text-ink-500">{user?.role}</p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="mt-2 w-full justify-start"
            onClick={() => void logout()}
          >
            Log out
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-ink-200 bg-white px-4">
          <Button
            variant="ghost"
            size="sm"
            className="lg:hidden"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open navigation"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeWidth="2" d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </Button>

          <Link to="/" className="text-sm text-ink-500 hover:text-ink-900">
            Back to site
          </Link>

          <span className="ml-auto text-xs text-ink-400">
            {import.meta.env.VITE_ENVIRONMENT ?? "local"}
          </span>
        </header>

        <main id="main" className="flex-1 p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
