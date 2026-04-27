/**
 * Loading-state placeholder that mirrors the rough silhouette of a
 * <PostCard> — type icon + author row + a couple of content lines + an
 * action bar. Pulse-animated via Tailwind's `animate-pulse`.
 *
 * Used by feed surfaces (home, explore, /tag/[name], /agents/[did]
 * posts tab) instead of a single centered spinner. Skeletons preserve
 * page height and give a much better perceived-performance feel: the
 * layout doesn't jump when posts arrive, and users see "where" content
 * is loading even before the network resolves.
 */
import type { ReactNode } from "react";

interface Props {
  /** How many skeleton cards to render. Defaults to 3 — enough to fill
   *  most viewports above the fold without being noisy. */
  count?: number;
}

function Card(): ReactNode {
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-background-light dark:bg-slate-900/40 p-4 animate-pulse">
      {/* Author row: avatar circle + name/time stack + type badge */}
      <div className="flex items-center gap-3 mb-3">
        <div className="w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-800" />
        <div className="flex-1 space-y-1.5">
          <div className="h-3 w-32 rounded bg-slate-200 dark:bg-slate-800" />
          <div className="h-2 w-20 rounded bg-slate-200/60 dark:bg-slate-800/60" />
        </div>
        <div className="h-5 w-16 rounded-full bg-slate-200 dark:bg-slate-800" />
      </div>

      {/* Title */}
      <div className="h-4 w-2/3 rounded bg-slate-200 dark:bg-slate-800 mb-3" />

      {/* Content lines */}
      <div className="space-y-2 mb-4">
        <div className="h-3 w-full rounded bg-slate-200/80 dark:bg-slate-800/80" />
        <div className="h-3 w-11/12 rounded bg-slate-200/80 dark:bg-slate-800/80" />
        <div className="h-3 w-3/4 rounded bg-slate-200/80 dark:bg-slate-800/80" />
      </div>

      {/* Action bar */}
      <div className="flex items-center gap-6 pt-3 border-t border-slate-200/60 dark:border-slate-800/60">
        <div className="h-3 w-8 rounded bg-slate-200 dark:bg-slate-800" />
        <div className="h-3 w-8 rounded bg-slate-200 dark:bg-slate-800" />
        <div className="h-3 w-8 rounded bg-slate-200 dark:bg-slate-800" />
        <div className="h-3 w-8 rounded bg-slate-200 dark:bg-slate-800" />
      </div>
    </div>
  );
}

export function PostCardSkeleton({ count = 3 }: Props = {}) {
  return (
    <div
      className="space-y-3"
      role="status"
      aria-label="Loading posts"
      aria-live="polite"
    >
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} />
      ))}
    </div>
  );
}
