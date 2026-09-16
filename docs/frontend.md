# Frontend

React 18, Vite, TypeScript, Tailwind 4. One bundle serves both the public
marketing site and the authenticated application, so "Log in" is an in-app
navigation rather than a page load and the two halves cannot drift apart
visually.

## Layout

```
src/
  api/          HTTP client, typed endpoint wrappers, response types
  components/
    ui/         shared primitives (buttons, badges, alerts, empty states)
    marketing/  site header and footer
    app/        authenticated shell and the route guard
  pages/
    marketing/  home, login, register
    app/        dashboard, statements, search, documents, reports, settings
  store/        auth state (Zustand)
  lib/          formatting helpers
  test/         Vitest unit and component tests
e2e/            Playwright journey
```

## Three decisions worth knowing

**Tokens are not in `localStorage`.** The access token lives in a module
variable in `api/client.ts`. A token in `localStorage` is readable by any script
that manages to run on the page, which turns a single XSS into a stolen session
that outlives the tab. The refresh token is persisted deliberately so a reload
does not log the user out; it is revocable server-side and single-use, so a
stolen copy is far less useful.

**A 401 triggers exactly one refresh, shared across concurrent requests.**
Refresh rotation is single-use on the server, so a second concurrent refresh
would be read as a replay and would revoke the whole session family. Ten
requests failing together must produce one refresh, not ten.

**Money is formatted from strings, never parsed.** Line item values are exact
decimals that exceed `Number.MAX_SAFE_INTEGER`. Anything that calls
`parseFloat` on one silently corrupts it, which is precisely what the backend's
`Numeric` column exists to prevent. `lib/format.ts` operates on the string.

## Missing data is never rendered as zero

A ratio that could not be computed shows "not computable", and an unscored
statement shows "Not assessed" rather than 0. Zero is a real and meaningful
value for most of these quantities, and conflating the two would invent a
finding that does not exist. The same distinction is carried in the backend and
in report rendering.

## Commands

All from `frontend/`.

| Command | Purpose |
|---|---|
| `npm run dev` | Dev server on 5173, proxying `/api` to the backend |
| `npm run build` | Production build with type checking |
| `npm run preview` | Serve the production build |
| `npm run lint` | ESLint, including `jsx-a11y` |
| `npm run typecheck` | TypeScript, no emit |
| `npm run test` | Vitest |
| `npm run e2e` | Playwright, needs the API running |

## Accessibility

The plan requires keyboard navigability, sufficient contrast, semantic HTML, and
alt text. What is implemented:

- A skip link on both layouts, the first thing a keyboard user reaches.
- A visible focus ring on every interactive element. Outlines are replaced, never
  removed.
- `eslint-plugin-jsx-a11y` in CI, which catches unlabelled controls and click
  handlers on non-interactive elements.
- Errors announced through `role="alert"`; everything else through
  `role="status"`. A polite region would let a failure sit unannounced until the
  user next moved focus.
- Buttons keep their accessible name while loading, using `aria-busy` rather
  than swapping the label out from under a screen reader.
- `prefers-reduced-motion` respected globally.
- Tables carry captions and `scope` attributes.

Not yet done: a full screen-reader pass, and automated contrast checking in CI.

## Testing

Unit and component tests run in jsdom and need nothing else. The Playwright
journey runs against a **production build** served by `vite preview`, not the
dev server, because a production bundle is what users get.

The API under test must run with `RATE_LIMIT_ENABLED=false`. The journey
registers several accounts from one address, and registration is limited to
5/hour, which is correct in production and makes a multi-test journey
impossible from a single host. The limits have their own backend tests.

## Two build gotchas

Both cost real debugging time and are worth knowing before touching the config.

**`vite preview` ignores `server.proxy`.** That block applies to the dev server
only. Preview needs its own `preview.proxy`, and without it every API call from
a built bundle 404s with nothing pointing at the cause. Both are declared in
`vite.config.ts` from one shared object.

**`vite preview` binds the name `localhost`,** which on some machines resolves
to `::1` only. A health check against `127.0.0.1` then never connects and the
server appears to hang. The Playwright config passes `--host 127.0.0.1`
explicitly.
