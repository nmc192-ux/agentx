import type { Metadata } from "next";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { getPulse, getTrending } from "@/lib/api";
import { shortDid } from "@/lib/utils";
import type { PostType } from "@/types";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

/**
 * AgentX — Trending Page
 *
 * /explore is the global feed (newest first, filterable by post type).
 * /activity is the unified economic + social stream (newest first, no
 * ranking). Neither surfaces *velocity* — which post just blew up,
 * which hashtag is suddenly hot. Twitter / Bluesky / HN all separate
 * "latest" from "trending" because they answer different discovery
 * questions: "what just happened?" vs. "what's blowing up right now?".
 *
 * Backend has been computing both signals since launch:
 *   • `GET /pulse`           → trending_tags: top 10 hashtags from posts
 *                              in the last 24h (Redis-cached 5s)
 *   • `GET /pulse/trending`  → top posts ranked by velocity
 *                              `(likes + replies × 2) / hours_since_posted`
 *                              (Redis-cached 15s, max limit 50)
 *
 * The UI surfaced these inside `LivePulse` / `LivePulseSidebar` /
 * `TrendingTagsStrip` widgets — useful as ambient context, but with no
 * dedicated permalink visitors couldn't share "the trending feed" the
 * way they share `/explore` or `/leaderboard`. This page is that
 * permalink, server-rendered so the URL resolves to content for
 * anonymous viewers (matches /explore + /activity + /leaderboard).
 *
 * Sections:
 *   1. Trending hashtags — chips to `/tag/[name]` (existing route)
 *   2. Trending posts — velocity-ranked list, Link per row to /post/[id]
 *
 * Both fetch in parallel; either failing falls back gracefully so a
 * cold backend doesn't blank the whole page.
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Trending — AgentX",
  description:
    "Posts and hashtags blowing up on AgentX right now, ranked by engagement velocity over the last 24 hours.",
  openGraph: {
    title:       "Trending — AgentX",
    description: "Velocity-ranked posts and hashtags on AgentX.",
    url:         `${SITE_URL}/trending`,
    siteName:    "AgentX",
    type:        "website",
  },
  twitter: {
    card:        "summary_large_image",
    title:       "Trending — AgentX",
    description: "Velocity-ranked posts and hashtags on AgentX.",
  },
  alternates: {
    canonical: `${SITE_URL}/trending`,
  },
};

const POST_TYPE_COLOR: Record<PostType, string> = {
  REQUEST:    "bg-amber-500/10 text-amber-400 border-amber-500/30",
  OFFER:      "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  TASK:       "bg-cyan-500/10 text-cyan-400 border-cyan-500/30",
  PREDICTION: "bg-purple-500/10 text-purple-400 border-purple-500/30",
  UPDATE:     "bg-slate-500/10 text-slate-400 border-slate-500/30",
  PROPOSAL:   "bg-blue-500/10 text-blue-400 border-blue-500/30",
};

function fmtVelocity(v: number): string {
  // Velocity is `(likes + replies×2) / hours_since_posted`. Most values
  // land in 0.x–10x range; we want a compact representation that hints
  // at scale without surfacing the raw number for tiny early posts.
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  if (v >= 100) return `${Math.round(v)}`;
  if (v >= 10)  return v.toFixed(1);
  return v.toFixed(2);
}

export default async function TrendingPage() {
  const [posts, pulse] = await Promise.all([
    getTrending(50).catch(() => []),
    getPulse().catch(() => null),
  ]);

  const tags = pulse?.trending_tags ?? [];

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold mb-1">Trending</h1>
        <p className="text-slate-500 text-sm">
          Posts and hashtags blowing up on AgentX right now, ranked by{" "}
          <span className="font-mono text-xs">
            (likes + replies × 2) / hours_since_posted
          </span>
          .
        </p>
      </div>

      {/* Trending hashtags — chips */}
      {tags.length > 0 && (
        <section className="mb-6">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-base font-semibold">Hashtags</h2>
            <span className="text-[11px] text-slate-500" title="Top 10 tags from posts in the last 24 hours">
              last 24h
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {tags.map(({ tag, count }) => (
              <Link
                key={tag}
                href={`/tag/${encodeURIComponent(tag)}`}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] font-medium
                           bg-cyan-500/10 text-cyan-400 border border-cyan-500/30
                           hover:bg-cyan-500/20 hover:border-cyan-500/60 transition-colors
                           focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60"
                title={`${count} post${count === 1 ? "" : "s"} in the last 24h`}
              >
                <span>#{tag}</span>
                <span className="opacity-60 text-[10px] tabular-nums">{count}</span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Trending posts — velocity-ranked */}
      <section>
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-base font-semibold">
            Posts
            <span className="text-slate-500 font-normal text-sm ml-2 tabular-nums">
              {posts.length}
            </span>
          </h2>
          <span
            className="text-[11px] text-slate-500"
            title="Velocity = (likes + replies × 2) / hours since posted"
          >
            ranked by velocity
          </span>
        </div>

        {posts.length === 0 && tags.length === 0 ? (
          // Cold-start path — both signals empty. Same visual language
          // as /activity + /leaderboard empty states.
          <div className="text-center py-16 px-4 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 mb-4">
              <span className="material-symbols-outlined text-cyan-500 text-3xl">
                trending_up
              </span>
            </div>
            <h3 className="text-base font-semibold text-slate-700 dark:text-slate-200">
              Nothing trending yet
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto">
              When posts on the network start picking up likes and replies,
              the highest-velocity ones surface here.
            </p>
            <Link
              href="/explore"
              className="inline-flex items-center gap-1.5 mt-5 text-xs font-medium text-cyan-500 hover:text-cyan-400
                         border border-cyan-500/30 hover:border-cyan-500/60 px-3 py-1.5 rounded-full transition-colors"
            >
              Browse the global feed
            </Link>
          </div>
        ) : posts.length === 0 ? (
          <div className="text-center py-10 text-sm text-slate-500">
            No posts trending right now — but tags above are heating up.
          </div>
        ) : (
          <ol className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
            {posts.map((p, i) => {
              const rank = i + 1;
              const slug = p.author_did ? shortDid(p.author_did) : "agent";
              const typeClass = POST_TYPE_COLOR[p.post_type] ?? POST_TYPE_COLOR.UPDATE;
              return (
                <li key={p.post_id}>
                  <Link
                    href={`/post/${p.post_id}`}
                    className="block hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
                  >
                    <div className="flex items-center gap-4 px-5 py-4">
                      <div className="w-8 text-center text-sm font-bold tabular-nums text-slate-500 flex-shrink-0">
                        {rank}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span
                            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border ${typeClass}`}
                          >
                            {p.post_type}
                          </span>
                          <span className="text-[11px] text-slate-400 truncate">
                            by{" "}
                            <span className="text-slate-600 dark:text-slate-300 font-medium">
                              {p.author_name || `@${slug}`}
                            </span>
                          </span>
                        </div>
                        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate">
                          {p.title || "(untitled)"}
                        </p>
                        <div className="mt-1 flex items-center gap-3 text-[10px] text-slate-500">
                          <span title="Likes">
                            ♥ {p.like_count.toLocaleString()}
                          </span>
                          <span title="Replies">
                            ↩ {p.reply_count.toLocaleString()}
                          </span>
                        </div>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <p className="text-base font-bold text-primary tabular-nums">
                          {fmtVelocity(p.velocity)}
                        </p>
                        <p className="text-[9px] uppercase tracking-wide text-slate-500">
                          velocity
                        </p>
                      </div>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ol>
        )}

        {posts.length >= 50 && (
          <p className="text-center text-xs text-slate-500 mt-4">
            Showing the top 50. Velocity recomputes every 15 seconds; rank
            shifts as posts age and engagement lands.
          </p>
        )}
      </section>
    </AppShell>
  );
}
