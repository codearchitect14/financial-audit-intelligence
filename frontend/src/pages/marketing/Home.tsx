/**
 * Marketing home page.
 *
 * Section order follows the plan: hero, trust bar, feature grid, how it works,
 * product preview, security, testimonials, and the footer (in Chrome.tsx).
 *
 * Illustrations are inline SVG rather than stock photography. The plan forbids
 * placeholder grey boxes in the final build, and an SVG built from the product
 * palette is sharp at every density, needs no licence, and adds nothing to page
 * weight. Replace with real product screenshots once the UI is final.
 */

import { ButtonLink } from "@/components/ui";

/* -------------------------------------------------------------------------- */
/* Hero                                                                        */
/* -------------------------------------------------------------------------- */
function Hero() {
  return (
    <section className="relative overflow-hidden bg-gradient-to-b from-brand-50 to-white">
      <div className="mx-auto grid max-w-7xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-2 lg:items-center lg:gap-16 lg:px-8 lg:py-28">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs font-semibold text-brand-700 ring-1 ring-brand-200">
            <span className="h-1.5 w-1.5 rounded-full bg-accent-500" aria-hidden="true" />
            Deterministic detection, explained in plain language
          </p>

          <h1 className="mt-5 text-4xl font-extrabold tracking-tight text-ink-900 sm:text-5xl lg:text-6xl">
            Find the numbers that do not add up.
          </h1>

          <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-600">
            Ledgerline screens financial statements with statistical and machine-learning
            checks, retrieves the filing text that explains them, and writes the narrative your
            reviewers would have written by hand. Every finding is reproducible.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <ButtonLink to="/register" size="lg">
              Start free analysis
            </ButtonLink>
            <ButtonLink to="/login" variant="secondary" size="lg">
              Log in
            </ButtonLink>
          </div>

          <p className="mt-4 text-sm text-ink-500">
            No card required. Runs on the public SEC corpus out of the box.
          </p>
        </div>

        <DashboardIllustration />
      </div>
    </section>
  );
}

/** An abstract rendering of the real dashboard, built from the product palette. */
function DashboardIllustration() {
  return (
    <div className="relative">
      <div className="rounded-2xl bg-white p-3 shadow-2xl ring-1 ring-ink-200">
        <div className="flex items-center gap-1.5 px-2 pb-3">
          {["#ef4444", "#f59e0b", "#10b981"].map((colour) => (
            <span
              key={colour}
              className="h-2.5 w-2.5 rounded-full"
              style={{ background: colour }}
              aria-hidden="true"
            />
          ))}
        </div>

        <svg viewBox="0 0 560 360" className="w-full rounded-lg bg-ink-50" role="img"
             aria-label="Product screenshot: a dashboard showing risk-scored statements, open findings, and a risk trend chart.">
          {/* Summary tiles */}
          {[
            { x: 16, label: "Statements", value: "12,480", accent: "#1f43e0" },
            { x: 154, label: "Open flags", value: "318", accent: "#b45309" },
            { x: 292, label: "High risk", value: "47", accent: "#c81e1e" },
            { x: 430, label: "Avg score", value: "34.2", accent: "#0d9488" },
          ].map((tile) => (
            <g key={tile.label}>
              <rect x={tile.x} y="16" width="114" height="62" rx="8" fill="#fff" stroke="#e0e5ec" />
              <text x={tile.x + 12} y="38" fontSize="9" fill="#6b7787">{tile.label}</text>
              <text x={tile.x + 12} y="62" fontSize="20" fontWeight="700" fill={tile.accent}>
                {tile.value}
              </text>
            </g>
          ))}

          {/* Trend chart */}
          <rect x="16" y="94" width="252" height="146" rx="8" fill="#fff" stroke="#e0e5ec" />
          <text x="28" y="114" fontSize="9" fill="#6b7787">Risk score trend</text>
          <polyline
            points="30,214 66,198 102,206 138,172 174,180 210,142 246,150"
            fill="none"
            stroke="#1f43e0"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <polygon
            points="30,214 66,198 102,206 138,172 174,180 210,142 246,150 246,228 30,228"
            fill="#1f43e0"
            opacity="0.08"
          />

          {/* Findings list */}
          <rect x="284" y="94" width="260" height="146" rx="8" fill="#fff" stroke="#e0e5ec" />
          <text x="296" y="114" fontSize="9" fill="#6b7787">Recent findings</text>
          {[
            { y: 128, w: 150, colour: "#c81e1e", label: "high" },
            { y: 154, w: 122, colour: "#b45309", label: "medium" },
            { y: 180, w: 168, colour: "#b45309", label: "medium" },
            { y: 206, w: 106, colour: "#4d5766", label: "low" },
          ].map((row) => (
            <g key={row.y}>
              <rect x="296" y={row.y} width={row.w} height="7" rx="3.5" fill="#c7cfdb" />
              <rect x="472" y={row.y - 3} width="58" height="14" rx="7" fill={row.colour} opacity="0.12" />
              <text x="481" y={row.y + 7} fontSize="7.5" fontWeight="600" fill={row.colour}>
                {row.label}
              </text>
            </g>
          ))}

          {/* Table */}
          <rect x="16" y="256" width="528" height="88" rx="8" fill="#fff" stroke="#e0e5ec" />
          {[276, 300, 324].map((y) => (
            <g key={y}>
              <rect x="30" y={y} width="140" height="7" rx="3.5" fill="#e0e5ec" />
              <rect x="200" y={y} width="86" height="7" rx="3.5" fill="#eef1f5" />
              <rect x="320" y={y} width="104" height="7" rx="3.5" fill="#eef1f5" />
              <rect x="460" y={y - 2} width="46" height="11" rx="5.5" fill="#1f43e0" opacity="0.1" />
            </g>
          ))}
        </svg>
      </div>

      <div className="absolute -bottom-5 -left-5 hidden rounded-xl bg-white px-4 py-3 shadow-lg ring-1 ring-ink-200 sm:block">
        <p className="text-xs font-medium text-ink-500">Findings from deterministic checks</p>
        <p className="text-lg font-bold text-ink-900">100% reproducible</p>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Trust bar                                                                   */
/* -------------------------------------------------------------------------- */
const TRUST_BADGES = [
  { label: "SOC 2 Type II", detail: "Controls audited" },
  { label: "AES-256", detail: "Encrypted at rest" },
  { label: "TLS 1.3", detail: "Encrypted in transit" },
  { label: "99.9%", detail: "Uptime target" },
  { label: "RBAC", detail: "Role-based access" },
];

function TrustBar() {
  return (
    <section className="border-y border-ink-200 bg-white py-8" aria-label="Security and compliance">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <p className="text-center text-xs font-semibold uppercase tracking-widest text-ink-400">
          Built for teams that have to show their work
        </p>
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {TRUST_BADGES.map((badge) => (
            <div
              key={badge.label}
              className="rounded-lg bg-ink-50 px-4 py-3 text-center ring-1 ring-ink-200"
            >
              <p className="text-sm font-bold text-ink-800">{badge.label}</p>
              <p className="mt-0.5 text-xs text-ink-500">{badge.detail}</p>
            </div>
          ))}
        </div>
        {/*
          These describe the target control set for the platform, not
          certifications already held. Replace with real attestations before
          publishing, and do not claim SOC 2 until the report exists.
        */}
        <p className="mt-4 text-center text-xs text-ink-400">
          Target control set. Attestation status is published in the trust centre.
        </p>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Features                                                                    */
/* -------------------------------------------------------------------------- */
const FEATURES = [
  {
    title: "Automated risk scoring",
    body: "Every statement is scored 0 to 100 from ratio screens, accounting identity checks, and peer outlier analysis. The score orders your queue; it never makes the call.",
    icon: "M3 17l6-6 4 4 8-8",
  },
  {
    title: "Semantic document search",
    body: "Ask in plain language and get the passages that answer it, retrieved by vector similarity over your filings and audit notes. No model call, no waiting.",
    icon: "M21 21l-4.35-4.35M17 10a7 7 0 11-14 0 7 7 0 0114 0z",
  },
  {
    title: "Explained findings",
    body: "Each flag carries its evidence: the observed value, the expected range, and the method. The AI explains what it means; it does not decide what is wrong.",
    icon: "M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L14.7 3.9a2 2 0 00-3.4 0z",
  },
  {
    title: "Benford digit analysis",
    body: "Leading-digit distributions tested across filing cohorts, with the sample size and chi-square reported so you can judge the strength of the signal yourself.",
    icon: "M4 19V5m6 14V9m6 10V3",
  },
  {
    title: "Accounting identity checks",
    body: "Assets equals liabilities plus equity is an identity, not a heuristic. Filings that fail it are surfaced immediately, with the discrepancy quantified.",
    icon: "M9 7h6m-6 5h6m-6 5h6M5 4h14a1 1 0 011 1v14a1 1 0 01-1 1H5a1 1 0 01-1-1V5a1 1 0 011-1z",
  },
  {
    title: "Audit-ready reports",
    body: "Generate a report where every figure comes from computed data and only the narrative is written by a model. Export as HTML or PDF, reproducible on demand.",
    icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.6L19 9.4V19a2 2 0 01-2 2z",
  },
];

function Features() {
  return (
    <section id="product" className="scroll-mt-20 bg-white py-20 lg:py-28">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="text-3xl font-bold tracking-tight text-ink-900 sm:text-4xl">
            Detection you can defend in a review meeting
          </h2>
          <p className="mt-4 text-lg text-ink-600">
            Statistics and machine learning decide what is worth looking at. The language model
            only explains what they found.
          </p>
        </div>

        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => (
            <article
              key={feature.title}
              className="rounded-xl bg-white p-6 ring-1 ring-ink-200 transition hover:shadow-lg hover:ring-brand-200"
            >
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d={feature.icon} />
                </svg>
              </span>
              <h3 className="mt-4 text-base font-semibold text-ink-900">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-600">{feature.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* How it works                                                                */
/* -------------------------------------------------------------------------- */
const STEPS = [
  {
    title: "Ingest",
    body: "Load SEC filings or upload your own statements and audit notes. Figures are normalised into exact decimals, never floats.",
  },
  {
    title: "Detect",
    body: "Ratio screens, accounting identities, Benford analysis, and peer outlier detection run over every statement. No model is involved.",
  },
  {
    title: "Retrieve",
    body: "Filing text is chunked and embedded locally, so you can search it semantically without spending a single API token.",
  },
  {
    title: "Explain",
    body: "Findings are batched into one model call, cached, and turned into narrative you can paste into a working paper.",
  },
];

function HowItWorks() {
  return (
    <section id="solutions" className="scroll-mt-20 bg-ink-50 py-20 lg:py-28">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="text-3xl font-bold tracking-tight text-ink-900 sm:text-4xl">
            From raw filings to a written finding
          </h2>
          <p className="mt-4 text-lg text-ink-600">
            Four steps. Only the last one costs an API call, and it is cached.
          </p>
        </div>

        <ol className="mt-14 grid gap-6 lg:grid-cols-4">
          {STEPS.map((step, index) => (
            <li key={step.title} className="relative rounded-xl bg-white p-6 ring-1 ring-ink-200">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-sm font-bold text-white">
                {index + 1}
              </span>
              <h3 className="mt-4 text-base font-semibold text-ink-900">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-600">{step.body}</p>
              {index < STEPS.length - 1 && (
                <span
                  className="absolute -right-3 top-10 hidden h-0.5 w-6 bg-ink-300 lg:block"
                  aria-hidden="true"
                />
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Security                                                                    */
/* -------------------------------------------------------------------------- */
const SECURITY_POINTS = [
  {
    title: "Tenant isolation at the query layer",
    body: "Every query is scoped to your organization in a single shared repository layer, not repeated in each endpoint. A resource belonging to another tenant does not resolve at all.",
  },
  {
    title: "Revocable sessions",
    body: "Access tokens are short-lived; refresh tokens are stored server-side as hashes and rotate on every use. Replaying a rotated token revokes the entire session family.",
  },
  {
    title: "Complete audit trail",
    body: "Every create, update, and delete is written to an append-only log with the actor, the action, and the time. Deleting a user never erases the record of what they did.",
  },
  {
    title: "Your data is not training data",
    body: "Only computed evidence from a finding reaches a model, never your raw dataset. Prompts are hashed for metering; the prompt text itself is never stored.",
  },
];

function Security() {
  return (
    <section id="security" className="scroll-mt-20 bg-ink-900 py-20 text-white lg:py-28">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid gap-12 lg:grid-cols-2 lg:gap-16">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-accent-400">
              Security and compliance
            </p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              Designed for data you are accountable for
            </h2>
            <p className="mt-4 text-lg text-ink-300">
              Financial statements under review are among the most sensitive documents an
              organization holds. The controls below are architectural, not configuration.
            </p>
            <div className="mt-8">
              <ButtonLink to="/register" size="lg">
                Review the architecture
              </ButtonLink>
            </div>
          </div>

          <dl className="grid gap-6 sm:grid-cols-2">
            {SECURITY_POINTS.map((point) => (
              <div key={point.title} className="rounded-xl bg-white/5 p-5 ring-1 ring-white/10">
                <dt className="text-sm font-semibold text-white">{point.title}</dt>
                <dd className="mt-2 text-sm leading-relaxed text-ink-300">{point.body}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Testimonials                                                                */
/* -------------------------------------------------------------------------- */
/*
 * SAMPLE CONTENT. These quotes, names, and companies are fictional placeholders
 * written to show the layout. Replace every one with a real, attributed,
 * permissioned quote before this page is published. Shipping invented
 * testimonials as though they were genuine is a misrepresentation, and in most
 * jurisdictions an actionable one.
 */
const TESTIMONIALS = [
  {
    quote:
      "The part that changed our review was the evidence on each flag. We can see the observed value and the expected range, so we are arguing about the finding rather than about the tool.",
    name: "Sample Name",
    title: "Audit Partner",
    company: "Sample Firm LLP",
  },
  {
    quote:
      "We ran it against a quarter we had already closed manually. It surfaced the two items we had caught, plus one we had not, and it explained why in language we could put in the file.",
    name: "Sample Name",
    title: "Group Financial Controller",
    company: "Sample Industrial Group",
  },
  {
    quote:
      "Being able to rerun detection and get identical results is the reason this cleared our methodology review. A tool that answers differently each time was never going to.",
    name: "Sample Name",
    title: "Head of Internal Audit",
    company: "Sample Bank",
  },
];

function Testimonials() {
  return (
    <section id="resources" className="scroll-mt-20 bg-white py-20 lg:py-28">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="text-3xl font-bold tracking-tight text-ink-900 sm:text-4xl">
            What review teams tell us
          </h2>
          <p className="mt-3 text-sm text-ink-400">
            Sample content. Replace with attributed customer quotes before launch.
          </p>
        </div>

        <div className="mt-14 grid gap-6 lg:grid-cols-3">
          {TESTIMONIALS.map((testimonial) => (
            <figure
              key={testimonial.quote}
              className="flex flex-col rounded-xl bg-ink-50 p-6 ring-1 ring-ink-200"
            >
              <blockquote className="flex-1 text-sm leading-relaxed text-ink-700">
                {testimonial.quote}
              </blockquote>
              <figcaption className="mt-5 flex items-center gap-3 border-t border-ink-200 pt-4">
                <span
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-sm font-bold text-brand-700"
                  aria-hidden="true"
                >
                  {testimonial.company.slice(0, 1)}
                </span>
                <span className="text-xs">
                  <span className="block font-semibold text-ink-900">{testimonial.name}</span>
                  <span className="block text-ink-500">
                    {testimonial.title}, {testimonial.company}
                  </span>
                </span>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Call to action                                                              */
/* -------------------------------------------------------------------------- */
function CallToAction() {
  return (
    <section className="bg-brand-600 py-16">
      <div className="mx-auto flex max-w-4xl flex-col items-center gap-6 px-4 text-center sm:px-6 lg:px-8">
        <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
          Score your first statement in about five minutes
        </h2>
        <p className="max-w-2xl text-lg text-brand-100">
          Create an organization, load a quarter of SEC filings, and see what the detectors find.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <ButtonLink to="/register" size="lg" variant="secondary">
            Create an account
          </ButtonLink>
          <ButtonLink
            to="/login"
            size="lg"
            variant="ghost"
            className="text-white hover:bg-brand-700"
          >
            Log in
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  return (
    <>
      <Hero />
      <TrustBar />
      <Features />
      <HowItWorks />
      <Security />
      <Testimonials />
      <CallToAction />
    </>
  );
}
