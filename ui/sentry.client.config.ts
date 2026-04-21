/**
 * Sentry — browser / client-side initialisation.
 * Picked up automatically by withSentryConfig (webpack injection).
 * No-op when NEXT_PUBLIC_SENTRY_DSN is unset.
 */
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

  // 10 % of transactions captured as performance traces.
  tracesSampleRate: 0.1,

  // Tag every event with the environment.
  environment: process.env.NODE_ENV,

  // Suppress Sentry's own console noise in development.
  debug: false,
});
