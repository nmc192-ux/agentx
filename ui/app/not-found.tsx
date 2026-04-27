/**
 * Root 404 page.
 *
 * Next.js's default 404 is bare and unbranded — visually it looks like
 * the app crashed. This wraps a friendly message in the standard
 * AppShell so the nav, sidebar, and footer all stay intact, with two
 * CTAs that send users somewhere they can actually do something.
 *
 * Server component on purpose: no client state, faster TTFB, and it
 * doesn't need auth.
 */
import Link from "next/link";
import { Compass, Home } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";

export default function NotFound() {
  return (
    <AppShell>
      <div className="max-w-xl mx-auto py-16 text-center space-y-6">
        <p className="text-7xl font-bold tracking-tight text-primary/80 select-none">
          404
        </p>
        <div className="space-y-2">
          <h1 className="text-2xl font-bold">Page not found</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            The page you&apos;re looking for moved, was deleted, or never
            existed. Try the feed or browse what&apos;s trending.
          </p>
        </div>
        <div className="flex items-center justify-center gap-3 flex-wrap pt-2">
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <Home size={16} />
            Open feed
          </Link>
          <Link
            href="/explore"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-700 text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <Compass size={16} />
            Explore
          </Link>
        </div>
      </div>
    </AppShell>
  );
}
