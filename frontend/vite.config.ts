/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const API_PROXY = {
  "/api": {
    target: process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // "@/..." imports keep the deep component tree readable and mean a file
    // can be moved without rewriting every relative path that reaches it.
    // import.meta.dirname rather than __dirname: the latter is unavailable
    // under the native config loader that Vite is moving to by default.
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  // The API is proxied so the browser sees one origin, which keeps cookies and
  // CORS behaving locally exactly as they do in production behind a single
  // domain.
  //
  // Declared for BOTH server and preview. `server.proxy` applies only to the
  // dev server; `vite preview` ignores it entirely and needs its own block, so
  // omitting this makes every API call from a built bundle 404 with no error
  // that points at the cause.
  server: {
    port: 5173,
    proxy: API_PROXY,
  },
  preview: {
    port: 4173,
    proxy: API_PROXY,
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        // Split the heavy, rarely-changing libraries out of the app chunk so
        // a code change does not force every visitor to re-download charting.
        manualChunks(id: string) {
          if (id.includes("node_modules/recharts") || id.includes("node_modules/d3-")) {
            return "charts";
          }
          if (
            id.includes("node_modules/react-dom") ||
            id.includes("node_modules/react-router") ||
            id.includes("node_modules/react/")
          ) {
            return "react";
          }
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Playwright specs live in e2e/ and are driven by Playwright, not Vitest.
    exclude: ["**/node_modules/**", "**/e2e/**"],
  },
});
