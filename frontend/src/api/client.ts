/**
 * HTTP client for the backend API.
 *
 * Three things here are load-bearing and worth reading before changing:
 *
 * 1. **Tokens live in memory, not localStorage.** A token in localStorage is
 *    readable by any script that manages to run on the page, which turns a
 *    single XSS into a stolen session that outlives the tab. The access token
 *    is held in a module variable; the refresh token persists only so a reload
 *    does not log the user out, and it is the thing the server can revoke.
 *
 * 2. **A 401 triggers exactly one refresh, shared.** Ten concurrent requests
 *    failing together must not fire ten refresh calls: refresh rotation is
 *    single-use on the server, so the second would be treated as a stolen
 *    token and would revoke the whole session.
 *
 * 3. **Errors are normalised.** Every backend failure has the same envelope,
 *    so the UI renders one error type rather than guessing at shapes.
 */

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

export class ApiError extends Error {
  // Declared and assigned explicitly rather than as constructor parameter
  // properties: those emit runtime code, which erasableSyntaxOnly forbids.
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** True when retrying after re-authenticating could plausibly succeed. */
  get isAuthError(): boolean {
    return this.status === 401;
  }

  get isPermissionError(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isRateLimited(): boolean {
    return this.status === 429;
  }
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const API_PREFIX = "/api/v1";

// Held in memory only. See the note at the top of this file.
let accessToken: string | null = null;

// The refresh token survives a reload so a user is not logged out by F5. It is
// the weaker of the two secrets to persist: it is revocable server-side, is
// single-use, and rotating it invalidates any stolen copy.
const REFRESH_KEY = "fai.refresh";

// A single in-flight refresh, shared by every request that hits a 401 at once.
let refreshInFlight: Promise<boolean> | null = null;

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler = () => {};

export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  onUnauthorized = handler;
}

export function setTokens(access: string | null, refresh?: string | null): void {
  accessToken = access;
  if (refresh === undefined) return;
  try {
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
    else localStorage.removeItem(REFRESH_KEY);
  } catch {
    // Private browsing and hardened configurations can make storage throw. The
    // session still works for this tab; it simply will not survive a reload.
  }
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

export function clearTokens(): void {
  setTokens(null, null);
}

async function parseError(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = response.statusText || "Request failed";
  let details: Record<string, unknown> | undefined;

  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details;
    }
  } catch {
    // A non-JSON error body (a proxy 502, say) still has to produce a usable
    // ApiError rather than throwing inside the error path.
  }

  return new ApiError(response.status, code, message, details);
}

/** Exchange the stored refresh token for a new pair. Returns success. */
async function refreshSession(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;

  try {
    const response = await fetch(`${BASE_URL}${API_PREFIX}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });

    if (!response.ok) {
      clearTokens();
      return false;
    }

    const tokens = (await response.json()) as {
      access_token: string;
      refresh_token: string;
    };
    setTokens(tokens.access_token, tokens.refresh_token);
    return true;
  } catch {
    return false;
  }
}

/** Refresh at most once concurrently, sharing the result. */
function refreshOnce(): Promise<boolean> {
  refreshInFlight ??= refreshSession().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Set for the auth endpoints, which must not attempt a token refresh. */
  skipAuth?: boolean;
  /** Return the raw Response rather than parsed JSON (report exports). */
  raw?: boolean;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken && !options.skipAuth) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  return fetch(`${BASE_URL}${API_PREFIX}${path}`, {
    ...options,
    headers,
    body:
      options.body instanceof FormData
        ? options.body
        : options.body !== undefined
          ? JSON.stringify(options.body)
          : undefined,
  });
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await send(path, options);

  if (response.status === 401 && !options.skipAuth) {
    const refreshed = await refreshOnce();
    if (refreshed) {
      response = await send(path, options);
    } else {
      clearTokens();
      onUnauthorized();
      throw await parseError(response);
    }
  }

  if (!response.ok) throw await parseError(response);

  if (options.raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "DELETE" }),
};

/** Build a query string, omitting empty values so filters stay clean. */
export function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
