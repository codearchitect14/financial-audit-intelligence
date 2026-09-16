# Frontend

React 18, Vite, TypeScript, Tailwind 4. Serves both the public marketing site
and the authenticated application from one bundle.

See [../docs/frontend.md](../docs/frontend.md) for the architecture, the
accessibility notes, and two build gotchas worth knowing before touching
`vite.config.ts`.

## Commands

```bash
npm run dev        # dev server on 5173, proxying /api to the backend
npm run build      # production build with type checking
npm run preview    # serve the production build
npm run lint       # ESLint, including jsx-a11y
npm run typecheck  # TypeScript, no emit
npm run test       # Vitest
npm run e2e        # Playwright (needs the API running)
```

Copy `.env.example` to `.env` before the first run. Everything prefixed `VITE_`
is inlined into the built bundle and is therefore public: never put a secret in
it.
