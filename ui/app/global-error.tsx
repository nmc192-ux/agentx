"use client";
/**
 * Global error boundary — required by @sentry/nextjs for App Router.
 * Captures unhandled errors that escape all nested error.tsx boundaries.
 */
import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en" className="dark">
      <body className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-950 text-slate-100">
        <h2 className="text-xl font-semibold">Something went wrong</h2>
        <p className="text-sm text-slate-400">
          The error has been reported automatically.
        </p>
        <button
          onClick={reset}
          className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-2
                     text-sm hover:bg-slate-700 transition-colors"
        >
          Try again
        </button>
      </body>
    </html>
  );
}
