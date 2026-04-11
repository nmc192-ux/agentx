import type { NextConfig } from "next";

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
      {
        source: "/api/:path*",
        destination: `${apiBase}/:path*`,
      },
    ];
  },
};

export default nextConfig;
