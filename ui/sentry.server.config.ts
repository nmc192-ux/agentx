/**
 * Sentry — Node.js server-side initialisation.
 * Loaded via instrumentation.ts (register → NEXT_RUNTIME === "nodejs").
 * No-op when NEXT_PUBLIC_SENTRY_DSN is unset.
 */
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

  tracesSampleRate: 0.1,

  environment: process.env.NODE_ENV,

  debug: false,
});
