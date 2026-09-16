import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// React Testing Library does not auto-clean when globals are enabled through
// Vitest rather than Jest, and a leaked DOM makes the next test see stale
// elements and fail for a reason unrelated to its subject.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Each test starts with empty storage. A refresh token left behind by one test
// would silently change how the API client behaves in the next.
beforeEach(() => {
  localStorage.clear();
});

// jsdom implements neither of these, and Recharts' ResponsiveContainer and any
// media query in the tree will throw without them.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
