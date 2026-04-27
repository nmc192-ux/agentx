"use client";
/**
 * Root error boundary.
 *
 * Catches any unhandled exception in a server or client component and
 * renders a recoverable shell instead of Next.js's default red box.
 * Must be a client component (Next.js requirement for error.tsx) and
 * accept the {error, reset} props.
 *
 * `error.digest` is the per-crash hash Next.js logs to the server —
 * including it lets the user reference a specific incident if they
 * report it.
 */
import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle, RotateCw, Home } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // Surface to the console so the dev panel / Sentry instrumentation
  // both pick it up. Sentry's own ErrorBoundary will already wrap this
  // in production, but we still want the console line.
  useEffect(() => {
    console.error("App error boundary caught:", error);
  }, [error]);

  return (
    <AppShell>
      <div className="max-w-xl mx-auto py-12 text-center space-y-5">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-red-500/10 text-red-500">
          <AlertTriangle size={28} />
        </div>
        <div className="space-y-2">
          <h1 className="text-2xl font-bold">Something went wrong</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            An unexpected error broke this page. You can retry, or head
            back to the feed.
          </p>
          {error.digest && (
            <p className="text-[11px] font-mono text-slate-400">
              ref: {error.digest}
            </p>
          )}
        </div>
        <div className="flex items-center justify-center gap-3 flex-wrap pt-2">
          <button
            type="button"
            onClick={reset}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <RotateCw size={16} />
            Try again
          </button>
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-700 text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <Home size={16} />
            Back to feed
          </Link>
        </div>
      </div>
    </AppShell>
  );
}
