import { defineConfig, devices } from "@playwright/test";

/**
 * Browser-agent tests (Sprint 18). They need a running local stack: the UI
 * at E2E_BASE_URL (default http://localhost:3000; the API's CORS_ORIGINS
 * must allow it) built with NEXT_PUBLIC_API_URL=E2E_API_URL. The usual way is
 * `platform/.venv/bin/python platform/scripts/join_e2e_check.py`, which
 * starts both against a throwaway database and runs `npm run test:e2e`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    trace: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
