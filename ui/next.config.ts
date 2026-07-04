import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  // ── Standalone output ───────────────────────────────────────────────────────
  // Emits a self-contained server.js + node_modules subset under .next/standalone.
  // Required for the Docker multi-stage build in ui/Dockerfile.
  // Has no effect on `npm run dev` or `npm run build` without Docker.
  output: "standalone",

  // ── API proxy (development + Docker) ───────────────────────────────────────
  // Proxies /api/* to the FastAPI backend so the browser avoids CORS in dev.
  // In Docker, Next.js server-side calls go to http://api:8000 directly.
  async rewrites() {
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    return [
      // A2A discovery — route the two .well-known paths to the FastAPI backend
      // that actually serves them. Mirrors the production vercel.json rewrite
      // so dev/Docker behave like prod. Exact paths only (no wildcard) so no
      // other /.well-known/* path is affected.
      {
        source: "/.well-known/agent.json",
        destination: `${apiBase}/.well-known/agent.json`,
      },
      {
        source: "/.well-known/skill.md",
        destination: `${apiBase}/.well-known/skill.md`,
      },
      {
        source: "/api/:path*",
        destination: `${apiBase}/:path*`,
      },
    ];
  },
};

export default withSentryConfig(nextConfig, {
  // ── Sentry build-time options ───────────────────────────────────────────────
  // Suppress the Sentry CLI output during local builds; keep it in CI.
  silent: !process.env.CI,

  // Source map upload requires SENTRY_AUTH_TOKEN — set in CI/CD only.
  // Locally this step is a no-op.
  authToken: process.env.SENTRY_AUTH_TOKEN,
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,

  // Keep source maps out of the browser bundle (upload only, don't serve them).
  sourcemaps: {
    deleteSourcemapsAfterUpload: true,
  },

  // Opt out of Sentry's anonymous build telemetry.
  telemetry: false,

  // Not using Vercel Cron Monitors.
  automaticVercelMonitors: false,
});
