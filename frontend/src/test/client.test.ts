/**
 * API client tests.
 *
 * The behaviours pinned down here are the ones that fail quietly and
 * expensively: a token written where a script can read it, and a burst of
 * concurrent refreshes that the server treats as token theft.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  api,
  clearTokens,
  getRefreshToken,
  queryString,
  setTokens,
  setUnauthorizedHandler,
} from "@/api/client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("queryString", () => {
  it("builds a query string", () => {
    expect(queryString({ limit: 10, offset: 0 })).toBe("?limit=10&offset=0");
  });

  it("omits empty values so filters stay clean", () => {
    expect(queryString({ a: 1, b: undefined, c: null, d: "" })).toBe("?a=1");
  });

  it("returns an empty string when nothing is set", () => {
    expect(queryString({ a: undefined })).toBe("");
  });

  it("encodes values", () => {
    expect(queryString({ q: "a b&c" })).toBe("?q=a+b%26c");
  });
});

describe("token storage", () => {
  beforeEach(() => {
    clearTokens();
  });

  it("never writes the access token to localStorage", () => {
    // An access token in localStorage turns a single XSS into a stolen session
    // that outlives the tab.
    setTokens("secret-access-token", "refresh-value");

    const stored = JSON.stringify(localStorage);
    expect(stored).not.toContain("secret-access-token");
  });

  it("persists the refresh token so a reload does not log the user out", () => {
    setTokens("access", "refresh-value");
    expect(getRefreshToken()).toBe("refresh-value");
  });

  it("clears both on logout", () => {
    setTokens("access", "refresh-value");
    clearTokens();
    expect(getRefreshToken()).toBeNull();
  });

  it("survives a storage backend that throws", () => {
    // Private browsing and hardened configurations make localStorage throw.
    // The session must still work for the current tab.
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });

    expect(() => setTokens("access", "refresh")).not.toThrow();
    spy.mockRestore();
  });
});

describe("error normalisation", () => {
  beforeEach(() => {
    clearTokens();
  });

  it("turns the shared error envelope into an ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { code: "not_found", message: "No such statement." } }, 404),
      ),
    );

    await expect(api.get("/statements/x")).rejects.toMatchObject({
      status: 404,
      code: "not_found",
      message: "No such statement.",
    });
  });

  it("still produces a usable error for a non-JSON body", async () => {
    // A proxy 502 returns HTML. The error path must not itself throw.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>gateway</html>", { status: 502 })),
    );

    const error = (await api.get("/anything").catch((exception) => exception)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
  });

  it("classifies statuses for the UI", () => {
    expect(new ApiError(401, "x", "y").isAuthError).toBe(true);
    expect(new ApiError(403, "x", "y").isPermissionError).toBe(true);
    expect(new ApiError(404, "x", "y").isNotFound).toBe(true);
    expect(new ApiError(429, "x", "y").isRateLimited).toBe(true);
  });
});

describe("token refresh", () => {
  beforeEach(() => {
    clearTokens();
    setUnauthorizedHandler(() => {});
  });

  it("refreshes once and retries the original request", async () => {
    setTokens("expired-token", "valid-refresh");

    const fetchMock = vi
      .fn()
      // The original request, rejected.
      .mockResolvedValueOnce(jsonResponse({ error: { code: "unauthenticated", message: "x" } }, 401))
      // The refresh.
      .mockResolvedValueOnce(
        jsonResponse({ access_token: "new-access", refresh_token: "new-refresh" }),
      )
      // The retry.
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/protected")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(getRefreshToken()).toBe("new-refresh");
  });

  it("fires exactly one refresh for concurrent failures", async () => {
    // Refresh rotation is single-use on the server. A second concurrent
    // refresh would be read as a replay and would revoke the whole session.
    setTokens("expired-token", "valid-refresh");

    let refreshCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes("/auth/refresh")) {
        refreshCalls += 1;
        return jsonResponse({ access_token: "new-access", refresh_token: "new-refresh" });
      }
      // Every original request fails first; the retry carries the new token.
      return refreshCalls === 0
        ? jsonResponse({ error: { code: "unauthenticated", message: "x" } }, 401)
        : jsonResponse({ ok: true });
    });
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    await Promise.all([api.get("/a"), api.get("/b"), api.get("/c"), api.get("/d")]);

    expect(refreshCalls).toBe(1);
  });

  it("clears the session and notifies when refresh fails", async () => {
    setTokens("expired-token", "stale-refresh");
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        String(url).includes("/auth/refresh")
          ? jsonResponse({ error: { code: "unauthenticated", message: "x" } }, 401)
          : jsonResponse({ error: { code: "unauthenticated", message: "x" } }, 401),
      ) as unknown as typeof fetch,
    );

    await expect(api.get("/protected")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
    expect(getRefreshToken()).toBeNull();
  });

  it("does not attempt a refresh for the auth endpoints", async () => {
    // A failed login must report "incorrect password", not silently try to
    // refresh a session the user does not have.
    setTokens(null, "some-refresh");

    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ error: { code: "unauthenticated", message: "bad" } }, 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      api.post("/auth/login", { email: "a@b.c", password: "x" }, { skipAuth: true }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("request construction", () => {
  beforeEach(() => clearTokens());

  it("attaches the bearer token", async () => {
    setTokens("the-token", null);
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/x");

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer the-token");
  });

  it("does not set Content-Type for FormData", async () => {
    // The browser has to generate the multipart boundary itself; setting the
    // header by hand breaks every upload.
    setTokens("the-token", null);
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    const form = new FormData();
    form.append("file", new Blob(["x"]), "x.txt");
    await api.post("/documents", form);

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers;
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("returns undefined for a 204", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(api.post("/auth/logout", {})).resolves.toBeUndefined();
  });
});
