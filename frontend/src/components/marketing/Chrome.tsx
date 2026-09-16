/**
 * Marketing site header and footer.
 *
 * The header is the only place a visitor can reach the application, so the
 * "Log in" control is always visible at every breakpoint, including inside the
 * mobile menu.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, ButtonLink } from "@/components/ui";
import { cn } from "@/lib/cn";

const NAV_LINKS = [
  { label: "Product", href: "/#product" },
  { label: "Solutions", href: "/#solutions" },
  { label: "Security", href: "/#security" },
  { label: "Pricing", href: "/pricing" },
  { label: "Resources", href: "/#resources" },
];

export function Logo({ className }: { className?: string }) {
  return (
    <Link
      to="/"
      className={cn("inline-flex items-center gap-2 font-bold tracking-tight", className)}
      aria-label="Ledgerline home"
    >
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden="true">
        <rect width="32" height="32" rx="7" className="fill-brand-600" />
        <path d="M8 22V10h3.2v9.2H18V22H8Z" fill="#fff" />
        <path d="M20 10h4v12h-4z" className="fill-accent-400" />
      </svg>
      <span className="text-lg">Ledgerline</span>
    </Link>
  );
}

export function MarketingHeader() {
  const [open, setOpen] = useState(false);

  // Closed on click rather than by an effect watching the location. Watching
  // the location means a setState inside an effect, which triggers a cascading
  // render, and it does not fire at all for the same-page hash links that make
  // up most of this menu.
  const closeMenu = () => setOpen(false);

  return (
    <header className="sticky top-0 z-40 border-b border-ink-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
        <Logo />

        <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
          {NAV_LINKS.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="rounded-md px-3 py-2 text-sm font-medium text-ink-600 transition hover:bg-ink-100 hover:text-ink-900"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="hidden items-center gap-2 lg:flex">
          <ButtonLink to="/login" variant="ghost" size="sm">
            Log in
          </ButtonLink>
          <ButtonLink to="/register" size="sm">
            Request demo
          </ButtonLink>
        </div>

        <Button
          variant="ghost"
          size="sm"
          className="lg:hidden"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="mobile-menu"
        >
          <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" aria-hidden="true">
            <path
              strokeLinecap="round"
              strokeWidth="2"
              d={open ? "M6 6l12 12M18 6L6 18" : "M4 7h16M4 12h16M4 17h16"}
            />
          </svg>
        </Button>
      </div>

      {open && (
        <div id="mobile-menu" className="border-t border-ink-200 bg-white lg:hidden">
          <nav className="space-y-1 px-4 py-3" aria-label="Main, mobile">
            {NAV_LINKS.map((link) => (
              <a
                key={link.label}
                href={link.href}
                onClick={closeMenu}
                className="block rounded-md px-3 py-2 text-sm font-medium text-ink-700 hover:bg-ink-100"
              >
                {link.label}
              </a>
            ))}
            <div className="flex gap-2 pt-2">
              <ButtonLink
                to="/login"
                variant="secondary"
                size="sm"
                className="flex-1"
                onClick={closeMenu}
              >
                Log in
              </ButtonLink>
              <ButtonLink to="/register" size="sm" className="flex-1" onClick={closeMenu}>
                Request demo
              </ButtonLink>
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}

const FOOTER_COLUMNS = [
  {
    heading: "Product",
    links: [
      { label: "Anomaly detection", href: "/#product" },
      { label: "Semantic search", href: "/#product" },
      { label: "Audit reports", href: "/#product" },
      { label: "Pricing", href: "/pricing" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "About", href: "/#solutions" },
      { label: "Careers", href: "/#solutions" },
      { label: "Contact", href: "/#resources" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { label: "Privacy", href: "/privacy" },
      { label: "Terms", href: "/terms" },
      { label: "Security", href: "/#security" },
    ],
  },
];

export function MarketingFooter() {
  return (
    <footer className="border-t border-ink-200 bg-ink-50">
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <Logo />
            <p className="mt-3 max-w-sm text-sm text-ink-500">
              Statistical detection first, AI explanation last. Reproducible findings for audit
              and controllership teams.
            </p>
            <div className="mt-4 flex gap-3">
              {["LinkedIn", "GitHub", "RSS"].map((network) => (
                <a
                  key={network}
                  href="/#resources"
                  className="rounded-md p-2 text-ink-400 transition hover:bg-ink-200 hover:text-ink-700"
                  aria-label={network}
                >
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden="true">
                    <circle cx="12" cy="12" r="9" />
                  </svg>
                </a>
              ))}
            </div>
          </div>

          {FOOTER_COLUMNS.map((column) => (
            <div key={column.heading}>
              <h2 className="text-sm font-semibold text-ink-900">{column.heading}</h2>
              <ul className="mt-3 space-y-2">
                {column.links.map((link) => (
                  <li key={link.label}>
                    <a href={link.href} className="text-sm text-ink-500 transition hover:text-ink-900">
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-10 flex flex-col gap-2 border-t border-ink-200 pt-6 text-xs text-ink-500 sm:flex-row sm:items-center sm:justify-between">
          <p>&copy; {new Date().getFullYear()} Ledgerline. All rights reserved.</p>
          <p>
            Analysis is produced by deterministic statistical checks. Output is decision support,
            not an audit opinion.
          </p>
        </div>
      </div>
    </footer>
  );
}
