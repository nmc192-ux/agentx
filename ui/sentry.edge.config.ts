/**
 * Sentry — Edge runtime initialisation.
 * Loaded via instrumentation.ts (register → NEXT_RUNTIME === "edge").
 * No-op when NEXT_PUBLIC_SENTRY_DSN is unset.
 */
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

  // Traces sample rate is lower for edge to minimise overhead.
  tracesSampleRate: 0.05,

  environment: process.env.NODE_ENV,

  debug: false,
});
