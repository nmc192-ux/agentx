import { PostCard } from "./PostCard";
import type { SocialPost } from "@/types";

/**
 * The six post types in the order they appear in PostTypeGuide and the
 * /explore filter chips. Color hexes mirror `postTypeColor()` in
 * types.ts — kept inline because FeedList stays a server component
 * (no "use client") and doesn't need the runtime helper.
 *
 * The empty state shows these as a row of muted dots: it teaches the
 * vocabulary at first contact, when the feed is silent, without having
 * to read the sidebar's PostTypeGuide.
 */
const EMPTY_STATE_TYPES: Array<{ label: string; color: string }> = [
  { label: "REQUEST",    color: "#EF4444" },
  { label: "OFFER",      color: "#22C55E" },
  { label: "TASK",       color: "#3B82F6" },
  { label: "PREDICTION", color: "#A855F7" },
  { label: "UPDATE",     color: "#F59E0B" },
  { label: "PROPOSAL",   color: "#F97316" },
];

export function FeedList({ posts }: { posts: SocialPost[] }) {
  if (!posts.length) {
    // Richer empty state. The previous one — "No posts yet" with no icon,
    // no guidance — felt broken on a fresh / network-blip feed. Now it
    // explains what the feed is, hints at the post-type vocabulary, and
    // points the eye toward the composer above (or the login button if
    // the composer is hidden for logged-out users).
    return (
      <div className="text-center py-16 px-4 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 mb-4">
          <span className="material-symbols-outlined text-cyan-500 text-3xl">
            rss_feed
          </span>
        </div>
        <h3 className="text-base font-semibold text-slate-700 dark:text-slate-200">
          The feed is quiet
        </h3>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto">
          Be the first to post — share a request, offer, or task to get the
          network moving.
        </p>
        <div
          className="flex items-center justify-center gap-3 mt-5 flex-wrap"
          aria-hidden
        >
          {EMPTY_STATE_TYPES.map((t) => (
            <span
              key={t.label}
              className="inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400"
              title={t.label}
            >
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{ background: t.color }}
              />
              {t.label}
            </span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {posts.map((p, i) => (
        <PostCard key={p.post_id} post={p} index={i} />
      ))}
    </div>
  );
}
