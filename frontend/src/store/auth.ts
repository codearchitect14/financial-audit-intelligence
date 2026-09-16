/**
 * Authentication state.
 *
 * Zustand rather than React context: the auth state is read by route guards,
 * the API client's unauthorized handler, and a dozen components, and a context
 * would re-render all of them on every change.
 *
 * Only the user profile is persisted. Tokens are handled by the API client,
 * which keeps the access token in memory. See `api/client.ts`.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { auth as authApi } from "@/api/endpoints";
import {
  clearTokens,
  getRefreshToken,
  hasAccessToken,
  setTokens,
} from "@/api/client";
import type { User } from "@/api/types";

interface AuthState {
  user: User | null;
  /** True until the initial session restore has finished. Route guards must
   *  wait for this, or a reload flashes the login page before restoring. */
  initialising: boolean;
  error: string | null;

  login: (email: string, password: string) => Promise<void>;
  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  restore: () => Promise<void>;
  clearError: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      initialising: true,
      error: null,

      login: async (email, password) => {
        set({ error: null });
        const tokens = await authApi.login({ email, password });
        setTokens(tokens.access_token, tokens.refresh_token);
        const user = await authApi.me();
        set({ user, initialising: false });
      },

      register: async (payload) => {
        set({ error: null });
        const result = await authApi.register(payload);
        setTokens(result.tokens.access_token, result.tokens.refresh_token);
        set({ user: result.user, initialising: false });
      },

      logout: async () => {
        const refresh = getRefreshToken();
        if (refresh) {
          // Best effort. A failed revoke must not trap the user in a logged-in
          // UI; the local session is cleared either way.
          try {
            await authApi.logout(refresh);
          } catch {
            /* ignored */
          }
        }
        clearTokens();
        set({ user: null, initialising: false });
      },

      restore: async () => {
        // A reload loses the in-memory access token but keeps the refresh
        // token, so the session is rebuilt from it.
        if (!getRefreshToken() && !hasAccessToken()) {
          set({ user: null, initialising: false });
          return;
        }

        try {
          // Any 401 here triggers the client's refresh-and-retry, so a single
          // call is enough to both restore the token and confirm the user is
          // still active.
          const user = await authApi.me();
          set({ user, initialising: false });
        } catch {
          clearTokens();
          set({ user: null, initialising: false });
        }
      },

      clearError: () => set({ error: null }),
    }),
    {
      name: "fai.auth",
      // The profile only. Persisting it avoids a blank header on reload while
      // the session is being restored; it is display data, not a credential,
      // and it is replaced by the server's answer a moment later.
      partialize: (state) => ({ user: state.user }),
      // Rehydration supplies a stale user, so initialising stays true until
      // restore() has confirmed the session against the server.
      onRehydrateStorage: () => (state) => {
        if (state) state.initialising = true;
      },
    },
  ),
);

/** Role ranking, mirroring the backend hierarchy in `core/permissions.py`. */
const ROLE_RANK: Record<string, number> = {
  viewer: 10,
  reviewer: 20,
  auditor: 30,
  admin: 40,
};

/**
 * True when the user holds at least the given role.
 *
 * This drives what the UI offers, never what it permits. The server enforces
 * every rule independently; hiding a button is a courtesy, not a control.
 */
export function hasRole(user: User | null, minimum: string): boolean {
  if (!user) return false;
  return (ROLE_RANK[user.role] ?? -1) >= (ROLE_RANK[minimum] ?? 99);
}
